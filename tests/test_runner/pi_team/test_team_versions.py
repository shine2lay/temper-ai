"""A team's version records (M4 ADR-M4-12 H, SW-36) and the token scan on what leaves a run
(SW-52): model-free, on throwaway git repositories and scripted members.

A record is written when the leader makes a version and when the team is done: the commit, the
start commit, every file with its sha256 and the diff against the start commit, cut at a cap
with a note saying so and where the whole diff is. Before it is stored, the version's file
names, the whole content of every changed file and the diff are scanned for login tokens: a hit
stores no files and no diff (the rules' names and the files only) and no branch is made from
it. A member's answer or message holding a token never leaves the run either.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from temper_ai.pi_agent import team_versions, token_scan
from temper_ai.pi_agent.ledger import reviews, versions
from temper_ai.pi_agent.team_leader import ProjectCopies
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts
from tests.test_runner.pi_team.leader_support import legacy_rounds as rounds

#: A fake login token of the access-token shape (built here so no file holds one whole).
FAKE = "sk-ant-" + "oat01-" + "Z" * 32
RUN_SECRET = "run-only-secret-" + "q" * 24


@pytest.fixture(autouse=True)
def _no_remembered_tokens():
    token_scan.forget_all()
    yield
    token_scan.forget_all()


def _copy(tmp_path: Path, files: dict[str, str] | None = None, *, source: bool = True):
    src = ls.project(tmp_path / "proj", files) if source else None
    copies = ProjectCopies(tmp_path / "team", str(src) if src else None)
    pdir = tmp_path / "team" / "members" / "lead"
    pdir.mkdir(parents=True)
    copies.ensure("lead", pdir)
    return src, copies, pdir


def _version(copies: ProjectCopies, pdir: Path, files: dict[str, str | bytes],
             act: str = "act-1") -> str:
    ws = ProjectCopies.worktree(pdir)
    for name, data in files.items():
        (ws / name).parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            (ws / name).write_bytes(data)
        else:
            (ws / name).write_text(data)
    return copies.commit_review("lead", pdir, act)


def _never_holds(record: object, *secrets: str) -> None:
    text = json.dumps(record, default=str)
    for secret in secrets:
        assert secret not in text


# --- what a record holds ------------------------------------------------------------------------


def test_a_record_holds_the_commit_the_start_commit_every_file_s_sha256_and_the_diff(tmp_path):
    src, copies, pdir = _copy(tmp_path)
    start = ls.git(src, "rev-parse", "HEAD")
    sha = _version(copies, pdir, {"README.md": "# Tiny\n", "app.py": "print('bye')\n"})

    rec = team_versions.build(copies, "lead", sha)

    assert rec["commit_sha"] == sha and rec["start_commit"] == start
    assert rec["files"] == [
        {"path": "README.md", "sha256": hashlib.sha256(b"# Tiny\n").hexdigest()},
        {"path": "app.py", "sha256": hashlib.sha256(b"print('bye')\n").hexdigest()}]
    assert rec["files_total"] == 2
    assert "+# Tiny" in rec["diff"] and "-print('hello')" in rec["diff"]
    assert rec["truncated"] is False and rec["note"] is None and rec["scan"] is None
    assert rec["diff_bytes"] == len(rec["diff"].encode())


def test_a_diff_past_the_cap_is_cut_and_the_record_says_where_the_whole_diff_is(
        tmp_path, monkeypatch):
    monkeypatch.setattr(team_versions, "MAX_DIFF_BYTES", 64)
    src, copies, pdir = _copy(tmp_path)
    start = ls.git(src, "rev-parse", "HEAD")
    sha = _version(copies, pdir, {"README.md": "".join(f"line {i}\n" for i in range(50))})

    rec = team_versions.build(copies, "lead", sha)

    assert rec["truncated"] is True
    assert len(rec["diff"].encode()) == 64 and rec["diff_bytes"] > 64
    assert rec["note"] == (f"the diff is cut at 64 of {rec['diff_bytes']} bytes; the whole "
                           "diff is on the trial's branch once the team is done, or in the "
                           f"leader's kept copy (git diff {start[:12]} {sha[:12]})")
    assert len(rec["files"]) == 2  # the files are all there whatever the diff's cut


def test_a_team_that_started_empty_diffs_against_its_first_commit(tmp_path):
    _src, copies, pdir = _copy(tmp_path, source=False)
    sha = _version(copies, pdir, {"README.md": "# New\n"})

    rec = team_versions.build(copies, "lead", sha)

    assert rec["start_commit"] is None and "+# New" in rec["diff"]
    assert [f["path"] for f in rec["files"]] == ["README.md"]


# --- a version holding a token is withheld (SW-36, SW-52) ---------------------------------------


@pytest.mark.parametrize("files, where, rule", [
    # a text file: found in the file and again in the diff
    ({"notes/secret.txt": f"key={FAKE}\n"}, ["file notes/secret.txt", "the diff"],
     "anthropic_oauth_access_token"),
    # a binary file: the diff only names it, the file's whole content is read
    ({"blob.bin": b"\x00\x01" + FAKE.encode() + b"\xff" * 8}, ["file blob.bin"],
     "anthropic_oauth_access_token"),
    # a file whose name is the token: named without it
    ({f"{FAKE}.txt": "nothing inside\n"}, ["the file names", "the diff"],
     "anthropic_oauth_access_token"),
    ({"run.txt": f"handed over: {RUN_SECRET}\n"}, ["file run.txt", "the diff"],
     token_scan.RUN_TOKEN),
], ids=["text-file", "binary-file", "file-name", "the-run-s-own-token"])
def test_a_version_holding_a_login_token_stores_no_files_no_diff_and_names_only_the_rules(
        tmp_path, files, where, rule):
    token_scan.remember(RUN_SECRET)
    _src, copies, pdir = _copy(tmp_path)
    sha = _version(copies, pdir, files)

    rec = team_versions.build(copies, "lead", sha)

    assert rec["files"] == [] and rec["diff"] == "" and rec["truncated"] is False
    assert rec["scan"]["refused"] is True and list(rec["scan"]["rules"]) == [rule]
    assert rec["scan"]["paths"] == where
    assert rec["note"].startswith("withheld: this version holds ")
    assert f"login-token match(es) ({rule} x" in rec["note"]
    assert rec["note"].endswith("none of its files or diff was stored, and no branch is made "
                                "from it")
    assert rec["commit_sha"] == sha and rec["files_total"] >= 1
    _never_holds(rec, FAKE, RUN_SECRET)
    assert team_versions.withheld(rec)


def test_a_deleted_file_that_held_a_token_is_not_brought_out_again(tmp_path):
    """The scan reads what the version brings out: a file the version deletes isn't in it."""
    _src, copies, pdir = _copy(tmp_path, {"app.py": "print('hello')\n", "old.txt": "fine\n"})
    (ProjectCopies.worktree(pdir) / "old.txt").unlink()
    sha = _version(copies, pdir, {"README.md": "# Tiny\n"})
    rec = team_versions.build(copies, "lead", sha)
    assert rec["scan"] is None and "-fine" in rec["diff"]


# --- the team writes its records; team_version serves the newest -------------------------------


def _rows(led, run_id) -> list[dict]:
    return ls.table(led, versions, run_id)


def test_the_leader_s_version_and_the_done_version_are_recorded_and_the_newest_is_served(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["keep_going", "done"])
    src = ls.project(tmp_path / "proj")
    team = ls.open_leader(led, box, run_id=run_id, source=src)
    out = team.drive(ls.Context())
    assert out.status == "done", out.text

    made, no_branch = team.done_version(out.record)
    assert no_branch is None
    stored = sorted(_rows(led, run_id), key=lambda r: r["seq"])
    assert [(r["kind"], r["round"]) for r in stored] == [("review", 1), ("review", 2),
                                                         ("done", 2)]
    revs = ls.table(led, reviews, run_id)
    assert {r["review_id"] for r in stored if r["kind"] == "review"} == \
        {r["review_id"] for r in revs}
    assert all(r["member"] == "lead" for r in stored)
    assert stored[-1]["commit_sha"] == out.record["version"]["commit"] == made["commit_sha"]
    assert stored[-1]["start_commit"] == ls.git(src, "rev-parse", "HEAD")

    newest = team_versions.latest(led.engine, run_id, ts.HOST)
    view = team_versions.view(newest)
    assert view["kind"] == "done" and view["commit"] == out.record["version"]["commit"]
    assert {f["path"] for f in view["files"]} == {"README.md", "app.py"}
    assert "+# Tiny v2" in view["diff"] and view["withheld"] is None
    # done again (a resumed node) stores nothing more
    team.done_version(out.record)
    assert len(_rows(led, run_id)) == 3
    ts.check_invariants(led, run_id)


def test_a_version_with_a_planted_token_is_withheld_and_no_branch_is_made_from_it(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["lead"][0].insert(1, ls.write("config.env", f"ANTHROPIC_TOKEN={FAKE}\n"))
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "done", out.text

    (review,) = ls.table(led, reviews, run_id)
    assert review["files"] in ({}, None, [])  # the reviewers were shown no file list
    made, no_branch = team.done_version(out.record)
    assert team_versions.withheld(made)
    assert no_branch == ("the version holds 2 login-token match(es) "
                         "(anthropic_oauth_access_token x2) in file config.env, the diff, so "
                         "no branch was made from it")
    for row in _rows(led, run_id):
        assert row["files"] == [] and row["diff"] == "" and row["scan"]["refused"] is True
    view = team_versions.view(team_versions.latest(led.engine, run_id, ts.HOST))
    assert view["withheld"] == {"rules": {"anthropic_oauth_access_token": 2},
                                "paths": ["file config.env", "the diff"]}
    _never_holds(ts.rows(led, run_id), FAKE)
    ts.check_invariants(led, run_id)


# --- answers and messages (SW-52) ---------------------------------------------------------------


def test_an_answer_holding_a_token_fails_its_turn_naming_the_rule_never_the_text(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"][0].append({"say": f"Found it in the logs: {FAKE}"})
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())

    assert out.status == "failed" and "builder" in out.text
    (failed,) = [t for t in ts.rows(led, run_id)["turns"] if t["state"] == "failed"]
    assert ("the answer was withheld: 1 login-token match(es) (anthropic_oauth_access_token x1)"
            " in builder's answer") in failed["error"]
    assert not failed["output"]
    _never_holds(ts.rows(led, run_id), FAKE)
    _never_holds(out.text, FAKE)
    ts.check_invariants(led, run_id)


def test_a_message_holding_a_token_is_refused_and_nothing_of_it_is_kept(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"][0].insert(0, {"send": {"to": "lead", "kind": "note",
                                                 "body": f"use this: {FAKE}"}})
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "done", out.text

    (sent,) = [s for s in ts.SENDS if s["member"] == "builder"
               and "body" in s["payload"] and FAKE in s["payload"]["body"]]
    assert sent["reply"]["ok"] is False
    assert sent["reply"]["detail"].startswith("refused: it holds 1 login-token match(es) "
                                              "(anthropic_oauth_access_token x1)")
    audits = [r for t in ts.rows(led, run_id)["turns"] for r in (t["refusals"] or [])]
    assert [a["token_refused"] for a in audits if "token_refused" in a] == [
        sent["reply"]["detail"]]
    _never_holds(ts.rows(led, run_id), FAKE)
    ts.check_invariants(led, run_id)
