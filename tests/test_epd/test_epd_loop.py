"""The EPD driver's bookkeeping: the backlog, a proposal's candidates, picking a bet, collecting a run.

Everything that talks to temper, standee, GitHub or git is patched out; what is under test is the
state the driver keeps on disk and the decisions it takes from it. The driver reads its root from
EPD_WORKSPACES at import, so each test imports it fresh into a temporary tree.
"""

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

DRIVER = Path(__file__).resolve().parents[2] / "configs" / "epd" / "bin" / "epd_loop.py"

PITCH = """# Bet {bet_id}: {title}

## Problem

Nothing on the Trade page says which expiries the roll rule considers.

## Invariant

{invariant}

## Success threshold

3 of 3 rejected strikes name the window.
"""


@pytest.fixture
def L(tmp_path, monkeypatch):
    """The driver, imported fresh against a temporary workspace tree, with the outside world stubbed."""
    ws = tmp_path / "workspaces"
    monkeypatch.setenv("EPD_WORKSPACES", str(ws))
    monkeypatch.setenv("EPD_REPO", "rollcall")
    spec = importlib.util.spec_from_file_location("epd_loop_under_test", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.pop("epd_loop_under_test", None)
    spec.loader.exec_module(mod)
    mod.LOOP_DIR.mkdir(parents=True)
    mod.BETS_DIR.mkdir()
    mod.REPORTS_DIR.mkdir()
    (mod.LOOP_DIR / "goals.md").write_text("Ship the roll job.\n")
    (mod.LOOP_DIR / "profile.md").write_text("RollCall: covered calls.\n")
    mod.ledger_write([])
    calls: dict[str, list] = {"standee_down": [], "release_task": [], "propose": [], "start": []}
    monkeypatch.setattr(mod, "standee_down", lambda env: calls["standee_down"].append(env))
    monkeypatch.setattr(mod, "release_task", lambda bet_id: calls["release_task"].append(bet_id))
    monkeypatch.setattr(mod, "require_tools", lambda *names: None)
    monkeypatch.setattr(mod, "run_cost", lambda run_id, upto=None: (None, None))
    monkeypatch.setattr(mod, "config_versions", lambda wf: {"workflow:" + wf: 1})
    monkeypatch.setattr(mod, "config_versions_all", lambda: {"workflow:epd_loop": 4})
    monkeypatch.setattr(mod, "cmd_propose", lambda keep, wait: calls["propose"].append((keep, wait)))
    monkeypatch.setattr(mod, "start_bet", lambda bet_id, keep, wait: calls["start"].append(bet_id))
    monkeypatch.setattr(mod, "get_run", lambda rid: {"status": "completed", "workflow_output": {}})
    mod._calls = calls
    return mod


def propose(L, round_id="r001", bets=("b001", "b002"), empty=("b003",), env="epd-r001"):
    """A proposal round as the driver leaves it once the run is collected: pitches on disk, ledger rows."""
    rdir = L.REPORTS_DIR / round_id
    rdir.mkdir()
    (rdir / "report.md").write_text("# Report\n\nThe roll window is invisible.\n")
    slots = list(bets) + list(empty)
    for b in slots:
        (L.BETS_DIR / b).mkdir()
    for b in bets:
        (L.BETS_DIR / b / "bet.md").write_text(PITCH.format(bet_id=b, title=f"Title of {b}", invariant=f"Invariant of {b}."))
    rd = {"round_id": round_id, "env": env, "url": "https://x", "slots": slots, "_run_id": "run-" + round_id}
    out = {
        "report_summary": "the window is invisible",
        "candidates": [{"bet_id": b, "title": f"Title of {b}", "invariant": f"Invariant of {b}.",
                        "threshold": f"threshold {b}", "rank": i + 1, "why": "because", "appetite_hours": 4}
                       for i, b in enumerate(bets)],
        "walk_1": "walk one", "walk_2": "walk two", "walk_3": "walk three",
        "_run_id": "run-" + round_id, "_versions": {"workflow:epd_propose": 1},
    }
    L.finish_round(rd, out, keep=False)
    return rd


# ------------------------------------------------------------------ files --


def test_write_replaces_a_file_this_user_cannot_open_for_writing(L, tmp_path):
    p = L.LOOP_DIR / "bet.json"
    p.write_text("theirs")
    os.chmod(p, 0o444)  # the container's user wrote it; we can read it, not open it for writing
    L.write(p, "ours")
    assert p.read_text() == "ours"
    assert stat.S_IMODE(p.stat().st_mode) == 0o666
    assert not list(L.LOOP_DIR.glob(".bet.json.*.tmp"))


# ---------------------------------------------------------------- backlog --


def test_backlog_reads_sections_in_order_with_notes_and_ignores_prose(L):
    L.ensure_backlog()
    assert L.read(L.BACKLOG).startswith("# Backlog")
    assert L.backlog() == [] and L.backlog_lines() == []
    L.write(L.BACKLOG, "# Backlog\n\nb004  the one that matters\n\n## Queue\n- b002\n1. b009 -- after b002\n"
                       "not a bet: b001 is mentioned here\n\n## Later\nb011  when fills ship\n\n## Declined\n"
                       "b006  too broad\n* b005  \u2192 recorded 2026-09-21 10:00 UTC\n")
    # lines above any heading are the queue; `## Later` is the owner's own and left alone
    assert L.backlog() == [("b004", "the one that matters"), ("b002", ""), ("b009", "after b002")]
    assert L.backlog_lines() == [
        ("queue", "b004", "the one that matters", ""), ("queue", "b002", "", ""), ("queue", "b009", "after b002", ""),
        ("declined", "b006", "too broad", ""), ("declined", "b005", "", "recorded 2026-09-21 10:00 UTC")]
    L.backlog_mark("queue", "b002", "taken now")
    assert [b for b, _ in L.backlog()] == ["b004", "b009"]
    text = L.read(L.BACKLOG)
    assert "- b002  \u2192 taken now\n" in text and "not a bet" in text and "b011  when fills ship" in text
    L.backlog_append("queue", "b012")
    L.backlog_append("declined", "b013  no")
    lines = L.read(L.BACKLOG).splitlines()
    assert lines[lines.index("not a bet: b001 is mentioned here") + 1] == "b012", "appended at the end of its section"
    assert lines[-1] == "b013  no"
    assert [b for b, _ in L.backlog()] == ["b004", "b009", "b012"]


def test_approve_queues_once_and_reject_records_without_removing(L):
    propose(L)
    L.approve("b002", None)
    L.approve("b001", "second, after b002")
    L.approve("b002", None)  # already there
    assert L.backlog() == [("b002", ""), ("b001", "second, after b002")]
    with pytest.raises(SystemExit):
        L.approve("b003", None)  # an empty slot: nothing was pitched there
    L.reject("b001", "too broad")
    assert L.backlog() == [("b002", "")], "the queue line stays, marked as overtaken by the decline"
    lines = [(s, b, why, mark.split(" ")[0]) for s, b, why, mark in L.backlog_lines()]
    assert lines == [("queue", "b002", "", ""), ("queue", "b001", "second, after b002", "declined"),
                     ("declined", "b001", "too broad", "recorded")]
    row = {r["bet_id"]: r for r in L.ledger_rows()}["b001"]
    assert row["status"] == "rejected" and row["outcome"] == "declined: too broad"
    assert "Declined on" in L.read(L.BETS_DIR / "b001" / "decision.md")
    assert (L.BETS_DIR / "b001" / "bet.md").exists(), "nothing on disk goes"
    decisions = [json.loads(ln) for ln in L.DECISIONS.read_text().splitlines()]
    assert decisions[-1]["decision"] == "reject" and decisions[-1]["where"] == "cli"
    assert L.pick_bet() == "b002"
    assert L.backlog() == []
    marks = {b: mark for s, b, _, mark in L.backlog_lines() if s == "queue"}
    assert marks["b002"].startswith("taken ") and marks["b001"].startswith("declined ")


def test_declines_written_in_the_file_are_recorded_with_the_reason(L, capsys):
    propose(L)
    L.write(L.BACKLOG, L.BACKLOG_HEADER + "b001  no: the window is a Settings bug\nb077  typo\nb002\n")
    L.record_declines()
    row = {r["bet_id"]: r for r in L.ledger_rows()}
    assert row["b001"]["status"] == "rejected" and row["b001"]["outcome"] == "declined: no: the window is a Settings bug"
    assert row["b002"]["status"] == "rejected" and row["b002"]["outcome"].startswith("declined: declined in backlog.md")
    decisions = [json.loads(ln) for ln in L.DECISIONS.read_text().splitlines()]
    assert [(d["bet_id"], d["decision"], d["where"]) for d in decisions] == [("b001", "reject", "backlog"), ("b002", "reject", "backlog")]
    marks = {b: mark for s, b, _, mark in L.backlog_lines() if s == "declined"}
    assert marks["b001"].startswith("recorded ") and marks["b002"].startswith("recorded ") and marks["b077"] == ""
    assert "b077, which has no pitch on file" in capsys.readouterr().out
    L.record_declines()  # idempotent: nothing new
    assert len(L.DECISIONS.read_text().splitlines()) == 2
    assert L.waiting_bets() == []


def test_a_declined_bet_listed_in_the_queue_is_reopened(L):
    propose(L)
    L.reject("b001", "not now")
    L.approve("b001", "changed my mind")
    assert L.pick_bet() == "b001"
    assert L.load_state("b001")["status"] == "approved"
    decisions = [(json.loads(ln)["decision"], json.loads(ln)["where"]) for ln in L.DECISIONS.read_text().splitlines()]
    assert decisions == [("reject", "cli"), ("reopen", "backlog"), ("approve", "backlog")]
    assert [(s, b, bool(m)) for s, b, _, m in L.backlog_lines()] == [("queue", "b001", True), ("declined", "b001", True)]


# --------------------------------------------------------------- proposal --


def test_finish_round_records_the_pitches_and_prunes_empty_slots(L):
    propose(L)
    assert not (L.BETS_DIR / "b003").exists(), "an empty slot is removed"
    rows = {r["bet_id"]: r for r in L.ledger_rows()}
    assert set(rows) == {"b001", "b002"}
    assert rows["b001"]["status"] == "proposed" and rows["b001"]["threshold"] == "threshold b001"
    assert rows["b001"]["title"] == "Title of b001"
    bet = json.loads((L.BETS_DIR / "b002" / "bet.json").read_text())
    assert bet["round"] == "r001" and bet["rank"] == 2 and bet["invariant"] == "Invariant of b002."
    rd = L.load_round("r001")
    assert rd["candidates"] == ["b001", "b002"] and rd["_collected"]
    assert (L.REPORTS_DIR / "r001" / "walk_2.md").read_text() == "walk two"
    assert L._calls["standee_down"] == ["epd-r001"]
    assert L.open_round() is None
    assert L.open_bet() is None, "candidates wait; nothing is open"
    assert L.waiting_bets() == ["b001", "b002"]
    assert L.report_path_for("b001") == L.REPORTS_DIR / "r001" / "report.md"


def test_report_path_for_a_bet_from_before_rounds(L):
    (L.BETS_DIR / "b000").mkdir()
    (L.BETS_DIR / "b000" / "bet.json").write_text(json.dumps({"title": "old"}))
    assert L.report_path_for("b000") == L.BETS_DIR / "b000" / "report.md"


def test_new_bet_ids_skip_taken_slots(L):
    propose(L)  # b001, b002 on the ledger; b003 pruned
    (L.BETS_DIR / "b004").mkdir()  # a directory, no ledger row: still taken
    assert L.new_bet_ids(3) == ["b003", "b005", "b006"]


# ------------------------------------------------------------------- pick --


def test_pick_bet_takes_the_top_line_and_signs_the_pitch_as_it_stands(L):
    propose(L)
    # the owner edits b002's invariant before listing it first
    (L.BETS_DIR / "b002" / "bet.md").write_text(PITCH.format(bet_id="b002", title="Title of b002",
                                                              invariant="Every rejection names the window."))
    L.ensure_backlog()
    L.backlog_append("queue", "b002  do this first")
    L.backlog_append("queue", "b001")
    assert L.pick_bet() == "b002"
    st = L.load_state("b002")
    assert st["status"] == "approved"
    assert st["stages"]["gate"]["edited"] == ["invariant"]
    assert st["stages"]["gate"]["invariant"] == "Every rejection names the window."
    bet = json.loads((L.BETS_DIR / "b002" / "bet.json").read_text())
    assert bet["invariant"] == "Every rejection names the window."
    decision = L.read(L.BETS_DIR / "b002" / "decision.md")
    assert "listed in backlog.md" in decision and "edited the pitch's invariant" in decision and "do this first" in decision
    assert L.backlog() == [("b001", "")]
    assert "b002  do this first  \u2192 taken " in L.read(L.BACKLOG), "the line stays, with the loop's receipt"
    assert L.open_bet() == "b002"
    assert L.waiting_bets() == ["b001"]
    row = json.loads(L.DECISIONS.read_text().splitlines()[-1])
    assert row == {**row, "bet_id": "b002", "kind": "bet", "decision": "approve", "where": "backlog", "note": "do this first"}


def test_pick_bet_marks_and_skips_lines_that_name_nothing_waiting(L):
    propose(L)
    L.write(L.BACKLOG, L.BACKLOG_HEADER.replace("## Declined", "b077\nb002\n\n## Declined"))
    assert L.pick_bet() == "b002"
    assert L.backlog() == []
    L.backlog_append("queue", "b002")
    assert L.pick_bet() is None, "b002 is open now, not waiting"
    assert L.backlog() == []
    marks = [(b, mark.split(" ")[0], mark.rsplit(": ", 1)[-1]) for s, b, _, mark in L.backlog_lines() if s == "queue"]
    assert marks[0] == ("b077", "skipped", "no pitch on file")
    assert marks[1][:2] == ("b002", "taken")
    assert marks[2] == ("b002", "skipped", "already approved")


# -------------------------------------------------------------------- run --


def test_run_proposes_when_nothing_is_on_file(L):
    L.cmd_run(keep=False, wait=False, propose=False, retry=False)
    assert L._calls["propose"] == [(False, False)] and L._calls["start"] == []


def test_run_waits_for_the_owner_when_candidates_are_not_listed(L, capsys):
    propose(L)
    L.cmd_run(keep=False, wait=False, propose=False, retry=False)
    assert L._calls["propose"] == [] and L._calls["start"] == []
    assert "waiting for your word: b001, b002" in capsys.readouterr().out


def test_run_starts_the_top_backlog_bet(L):
    propose(L)
    L.approve("b002", None)
    L.cmd_run(keep=False, wait=False, propose=False, retry=False)
    assert L._calls["start"] == ["b002"] and L._calls["propose"] == []
    assert L.load_state("b002")["status"] == "approved"


def test_run_propose_flag_proposes_whatever_the_backlog_holds(L):
    propose(L)
    L.approve("b001", None)
    L.cmd_run(keep=False, wait=False, propose=True, retry=False)
    assert L._calls["propose"] == [(False, False)] and L._calls["start"] == []
    assert L.backlog() == [("b001", "")]


def test_run_leaves_a_running_proposal_alone(L, monkeypatch):
    rd = {"round_id": "r001", "env": "epd-r001", "slots": ["b001"], "_run_id": "run-r001"}
    L.REPORTS_DIR.joinpath("r001").mkdir()
    L.save_round(rd)
    monkeypatch.setattr(L, "get_run", lambda rid: {"status": "running", "nodes": [{"name": "walks", "status": "running"}]})
    L.cmd_run(keep=False, wait=False, propose=False, retry=False)
    assert L._calls["propose"] == [] and L._calls["start"] == []
    assert L.open_round() == "r001"


def test_run_leaves_a_running_bet_alone_and_reports_a_failed_one(L, monkeypatch, capsys):
    propose(L)
    L.approve("b001", None)
    assert L.pick_bet() == "b001"
    st = L.load_state("b001")
    st["status"] = "running"
    st["stages"]["loop"] = {"_run_id": "run-b001"}
    L.save_state(st)
    monkeypatch.setattr(L, "get_run", lambda rid: {"status": "running", "nodes": []})
    L.cmd_run(keep=False, wait=False, propose=False, retry=False)
    assert L._calls["start"] == [] and L._calls["propose"] == []
    monkeypatch.setattr(L, "get_run", lambda rid: {"status": "failed", "error_message": "1 node(s) failed: build"})
    monkeypatch.setattr(L, "rate_limited", lambda rid: False)
    L.cmd_run(keep=False, wait=False, propose=False, retry=False)
    assert L._calls["start"] == [], "a failed run is not retried on its own"
    assert "ended failed: 1 node(s) failed: build" in capsys.readouterr().out
    L.cmd_run(keep=False, wait=False, propose=False, retry=True)
    assert L._calls["start"] == ["b001"], "--retry starts the same bet over"


# ---------------------------------------------------------------- collect --


def test_finish_loop_records_a_measured_bet_off_its_pitch(L):
    propose(L)
    L.approve("b001", None)
    L.pick_bet()
    st = L.load_state("b001")
    out = {"verdict": "kept", "vacuous_criteria": 0, "threshold_met": True, "outcome_summary": "3 of 3 name the window",
           "right_threshold": "yes", "shipped": "shipped", "merge_sha": "abcdef0123456789", "pr": "https://x/pull/9",
           "build_verdict": "approve", "implement_commit": "deadbee", "env_name": "epd-b001", "_run_id": "run-b001"}
    L.finish_loop(st, out, keep=False)
    row = {r["bet_id"]: r for r in L.ledger_rows()}["b001"]
    assert row["status"] == "kept" and row["title"] == "Title of b001" and row["threshold"] == "threshold b001"
    assert row["outcome"].startswith("kept: 3 of 3 name the window")
    assert L._calls["standee_down"] == ["epd-r001", "epd-b001"]
    assert L._calls["release_task"] == ["b001"]
    assert L.open_bet() is None
    assert L.previous_bet_id() is None, "no outcome.md on disk in this test; nothing to inherit"


def test_finish_loop_downgrades_a_vacuous_kept_and_keeps_a_shipped_bet_open(L):
    propose(L)
    L.approve("b001", None)
    L.pick_bet()
    st = L.load_state("b001")
    L.finish_loop(st, {"verdict": "kept", "vacuous_criteria": 2, "outcome_summary": "s", "shipped": "shipped",
                       "merge_sha": "abc"}, keep=True)
    assert L.ledger_rows()[0]["status"] == "iterate"
    assert L._calls["standee_down"] == ["epd-r001"], "--keep leaves the build's stack"
    # shipped, but measure never reported: the bet stays open for `stage measure`
    L.approve("b002", None)
    L.pick_bet()
    st = L.load_state("b002")
    L.finish_loop(st, {"shipped": "shipped", "merge_sha": "0123456789abcdef", "build_verdict": "approve"}, keep=False)
    row = {r["bet_id"]: r for r in L.ledger_rows()}["b002"]
    assert row["status"] == "shipped" and row["outcome"] == "shipped as 0123456789ab; not measured"
    assert L.open_bet() == "b002"
    assert L._calls["release_task"] == ["b001", "b002"]


def test_finish_loop_records_the_owners_no_on_the_pr(L):
    propose(L)
    L.approve("b001", None)
    L.pick_bet()
    st = L.load_state("b001")
    L.finish_loop(st, {"shipped": "changes_requested", "pr": "https://x/pull/3", "build_verdict": "approve"}, keep=False)
    assert L.ledger_rows()[0]["status"] == "changes_requested"
    assert L.open_bet() is None and L._calls["release_task"] == ["b001"]


def test_collect_round_failure_prunes_and_gives_up_on_the_round(L, monkeypatch):
    rdir = L.REPORTS_DIR / "r001"
    rdir.mkdir()
    for b in ("b001", "b002"):
        (L.BETS_DIR / b).mkdir()
    L.save_round({"round_id": "r001", "env": "epd-r001", "slots": ["b001", "b002"], "_run_id": "run-r001"})
    monkeypatch.setattr(L, "get_run", lambda rid: {"status": "failed", "error_message": "1 node(s) failed: walks"})
    monkeypatch.setattr(L, "rate_limited", lambda rid: False)
    with pytest.raises(SystemExit):
        L.collect_round("r001", keep=False)
    assert not (L.BETS_DIR / "b001").exists() and not (L.BETS_DIR / "b002").exists()
    assert L.load_round("r001")["_failed"]["why"] == "1 node(s) failed: walks"
    assert L.open_round() is None, "a failed round is not collected again; `run --propose` starts a new one"
    assert L._calls["standee_down"] == ["epd-r001"]
    assert L.new_round_id() == "r002"
