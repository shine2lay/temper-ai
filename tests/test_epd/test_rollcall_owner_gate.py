"""RollCall's owner-action gate for one release candidate (configs/epd/bin/rollcall_owner_gate.py).

docker and the judge are fakes here; the folders are temporary copies of the layout the gate reads
(corpus, harness, the role folder and the builders' mirror). Synthetic data only.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[2] / "configs" / "epd" / "bin"
SHA = "c" * 40
IMAGE = "rollcall:rollcall-staging"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


PINNED = ("entry.py", "owner_gate/__init__.py", "owner_gate/pairs.py")
#: The builders' harness folder: the pinned files plus what QA #228 F1 slipped past the pins.
HARNESS = {
    "entry.py": "print('entry')\n",
    "owner_gate/__init__.py": "",
    "owner_gate/pairs.py": "PAIRS = ()\n",
    "json.py": "# shadows the stdlib json: turns refused rows into ok\n",
    "owner_gate/__pycache__/pairs.cpython-312.pyc": "stale bytecode\n",
    "sitecustomize.py": "# runs at start-up\n",
    "DESIGN.md": "# design\n",
    "tests/test_pairs.py": "def test(): pass\n",
}


def snapshot(folder: Path, sid: str, captured_at: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sid}.json"
    path.write_text(json.dumps({"schema": "rollcall-owner-actions-snapshot/1", "snapshot_id": sid,
                                "captured_at": captured_at}))
    return path


@pytest.fixture
def og(tmp_path, monkeypatch):
    checks, skill = tmp_path / "checks", tmp_path / "skill"
    monkeypatch.setenv("ROLLCALL_OWNER_GATE_CHECKS", str(checks))
    monkeypatch.setenv("ROLLCALL_OWNER_GATE_SKILL", str(skill))
    monkeypatch.delenv("DEPLOY_RECORD_NOTES", raising=False)
    monkeypatch.syspath_prepend(str(BIN))
    sys.modules.pop("rollcall_owner_gate", None)
    og = importlib.import_module("rollcall_owner_gate")
    fixed = snapshot(checks / "corpus" / "fixed", "2026-01-02T150000Z", "2026-01-02T15:00:00Z")
    (checks / "corpus" / "MANIFEST.json").write_text(json.dumps({fixed.stem: digest(fixed)}))
    harness = checks / "harness"
    for rel, text in HARNESS.items():
        (harness / rel).parent.mkdir(parents=True, exist_ok=True)
        (harness / rel).write_text(text)
    for folder in (skill, checks / "judge"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "judge.py").write_text("# judge\n")
        (folder / "allowed.json").write_text('{"codes": []}\n')
    (skill / "pins.json").write_text(json.dumps({"files": {rel: digest(harness / rel) for rel in PINNED}}))
    monkeypatch.setattr(og, "now", lambda: datetime(2026, 1, 7, 18, 0, tzinfo=UTC))  # a Wednesday
    og.calls, og.built_at, og.judge_code, og.harness_code = [], SHA[:8], og.PASS, 0
    verdicts = {og.PASS: {"verdict": "pass", "expected": 3, "tried": 3, "refused": 1, "allowed_refusals": 1,
                          "blocked": 0, "not_exercisable": 0, "extra": 0, "blocked_items": []},
                og.BLOCK: {"verdict": "block", "expected": 3, "tried": 3, "refused": 1, "allowed_refusals": 0,
                           "blocked": 1, "not_exercisable": 0, "extra": 0, "blocked_items": [
                               {"snapshot_id": fixed.stem, "item_id": "rc-x", "action": "follow_mid",
                                "broker": "alpaca-live", "why": "refused_not_allowed", "code": "rule_floor_unknown"}]},
                og.CANNOT_JUDGE: {"verdict": "cannot_judge", "reason": "pins.json pins no harness file"}}

    def docker(*args, timeout):
        og.calls.append(args)
        if args[:2] == ("image", "inspect"):
            env = ["PATH=/usr/bin", f"ROLLCALL_COMMIT={og.built_at}"]
            return subprocess.CompletedProcess(args, 0, f"sha256:{'d' * 64} {json.dumps(env)}\n", "")
        if args[0] == "run":
            if og.harness_code == "timeout":
                raise subprocess.TimeoutExpired(args, timeout)
            out = Path(next(a for a in args if a.endswith(":/out")).rsplit(":", 1)[0])
            (out / "results.jsonl").write_text('{"type": "run"}\n')
            return subprocess.CompletedProcess(args, og.harness_code, "ran\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def run_judge(run, harness_exit):
        og.judged = (run, harness_exit)
        (run / "verdict.json").write_text(json.dumps(verdicts[og.judge_code]))
        return og.judge_code

    monkeypatch.setattr(og, "docker", docker)
    monkeypatch.setattr(og, "run_judge", run_judge)
    og.checks, og.skill, og.fixed = checks, skill, fixed
    return og


def records(og) -> list[dict]:
    return [json.loads(line) for line in (og.checks / "runs.jsonl").read_text().splitlines()]


def harness_argv(og) -> tuple[str, ...]:
    return next(c for c in og.calls if c[0] == "run")


def test_a_pass_runs_the_harness_offline_on_the_image_by_id_and_records_the_numbers(og):
    result = og.gate(SHA, IMAGE)
    assert result.code == og.PASS and "passed: tried 3, refused 1" in result.summary
    argv = harness_argv(og)
    assert argv[argv.index("--network") + 1] == "none" and "--read-only" in argv
    run = og.checks / "runs" / records(og)[0]["run_id"]
    assert f"{run / 'harness'}:/harness:ro" in argv and any(a.endswith("/snapshots:/snapshots:ro") for a in argv)
    assert not any(str(og.checks / "harness") + ":" in a for a in argv)  # never the builders' folder
    assert argv[argv.index("--entrypoint") + 1:argv.index("--entrypoint") + 6] == (
        "python", f"sha256:{'d' * 64}", "-I", "-B", "/harness/entry.py")
    assert f"sha256:{'d' * 64}" in argv and IMAGE not in argv  # by id, so a re-tag mid-run changes nothing
    assert not any(a.startswith("--env-file") for a in argv)
    [rec] = records(og)
    assert rec["sha"] == SHA and rec["verdict"] == "pass" and rec["code"] == 0
    assert (rec["tried"], rec["refused"], rec["blocked"], rec["not_exercisable"]) == (3, 1, 0, 0)
    assert isinstance(rec["ms"], int) and rec["snapshots"] == {"fixed": [og.fixed.stem], "latest": None}
    run = og.checks / "runs" / rec["run_id"]
    assert (run / "snapshots" / og.fixed.name).read_text() == og.fixed.read_text()
    assert og.judged == (run, 0)


def test_a_block_is_exit_1_and_names_the_blocked_pair(og):
    og.judge_code = og.BLOCK
    result = og.gate(SHA, IMAGE)
    assert result.code == og.BLOCK
    assert result.summary == "owner-action gate blocked 1: follow_mid on rc-x refused_not_allowed rule_floor_unknown"
    assert records(og)[0]["blocked_items"][0]["code"] == "rule_floor_unknown"


def test_judge_cannot_judge_is_exit_2_with_its_reason(og):
    og.judge_code = og.CANNOT_JUDGE
    result = og.gate(SHA, IMAGE)
    assert result.code == og.CANNOT_JUDGE and result.summary.endswith("cannot judge: pins.json pins no harness file")


def test_an_image_built_at_another_commit_cannot_be_judged_and_runs_nothing(og):
    og.built_at = "e" * 40
    result = og.gate(SHA, IMAGE)
    assert result.code == og.CANNOT_JUDGE and "not cccccccccccc" in result.record["reason"]
    assert not [c for c in og.calls if c[0] == "run"] and records(og)[0]["verdict"] == "cannot_judge"


def test_a_builders_copy_that_differs_from_rollcalls_cannot_be_judged(og):
    (og.checks / "judge" / "allowed.json").write_text('{"codes": [{"code": "anything"}]}\n')
    result = og.gate(SHA, IMAGE)
    assert result.code == og.CANNOT_JUDGE and "allowed.json" in result.record["reason"]
    assert og.calls == []


def test_a_fixed_snapshot_that_does_not_match_the_manifest_cannot_be_judged(og):
    og.fixed.write_text(og.fixed.read_text() + " ")
    result = og.gate(SHA, IMAGE)
    assert result.code == og.CANNOT_JUDGE and "MANIFEST" in result.record["reason"]


def test_the_newest_latest_capture_is_added_and_its_age_recorded(og):
    latest = og.checks / "corpus" / "latest"
    snapshot(latest, "latest-2026-01-05T160000Z", "2026-01-05T16:00:00Z")
    snapshot(latest, "latest-2026-01-06T160000Z", "2026-01-06T16:00:00Z")
    og.gate(SHA, IMAGE)
    rec = records(og)[0]
    assert rec["snapshots"]["latest"] == {"snapshot": "latest-2026-01-06T160000Z",
                                          "captured_at": "2026-01-06T16:00:00Z", "market_days_old": 1, "stale": False}
    assert sorted(p.name for p in (og.checks / "runs" / rec["run_id"] / "snapshots").iterdir()) == [
        f"{og.fixed.stem}.json", "latest-2026-01-06T160000Z.json"]


def test_a_latest_capture_older_than_3_market_days_still_runs_and_is_marked_stale(og):
    snapshot(og.checks / "corpus" / "latest", "latest-2025-12-31T160000Z", "2025-12-31T16:00:00Z")
    result = og.gate(SHA, IMAGE)
    assert result.code == og.PASS
    assert records(og)[0]["snapshots"]["latest"]["market_days_old"] == 5
    assert records(og)[0]["snapshots"]["latest"]["stale"] is True


def test_market_days_count_weekdays_only():
    sys.path.insert(0, str(BIN))
    og = importlib.import_module("rollcall_owner_gate")
    assert og.market_days_between(date(2026, 1, 2), date(2026, 1, 5)) == 1  # Fri -> Mon
    assert og.market_days_between(date(2026, 1, 5), date(2026, 1, 5)) == 0


def test_a_harness_past_its_ceiling_is_killed_and_the_judge_is_told(og):
    og.harness_code = "timeout"
    og.gate(SHA, IMAGE)
    assert any(c[0] == "kill" for c in og.calls) and og.judged[1] == 124


def test_every_run_appends_one_record_and_never_rewrites_an_earlier_one(og, monkeypatch):
    og.gate(SHA, IMAGE)
    first = (og.checks / "runs.jsonl").read_text()
    monkeypatch.setattr(og, "now", lambda: datetime(2026, 1, 7, 18, 5, tzinfo=UTC))
    og.judge_code = og.BLOCK
    og.gate(SHA, IMAGE)
    text = (og.checks / "runs.jsonl").read_text()
    assert text.startswith(first) and [r["code"] for r in records(og)] == [0, 1]


def test_the_record_goes_to_wt_deploys_notes_file_when_it_names_one(og, monkeypatch, tmp_path):
    notes = tmp_path / "notes.json"
    monkeypatch.setenv("DEPLOY_RECORD_NOTES", str(notes))
    og.gate(SHA, IMAGE)
    assert json.loads(notes.read_text())["owner_action_gate"]["tried"] == 3


# QA #228 F1: an unpinned json.py or stale .pyc in the builders' harness folder turned a block into a pass.

def test_the_harness_mounted_is_a_read_only_copy_of_only_the_pinned_files(og):
    og.gate(SHA, IMAGE)
    copy = og.checks / "runs" / records(og)[0]["run_id"] / "harness"
    files = sorted(p.relative_to(copy).as_posix() for p in copy.rglob("*") if not p.is_dir())
    assert files == sorted(PINNED)
    assert sorted(p.relative_to(copy).as_posix() for p in copy.rglob("*") if p.is_dir()) == ["owner_gate"]
    for rel in PINNED:
        assert (copy / rel).read_bytes() == (og.checks / "harness" / rel).read_bytes()
        assert (copy / rel).stat().st_mode & 0o777 == 0o444
    assert copy.stat().st_mode & 0o777 == 0o555 and (copy / "owner_gate").stat().st_mode & 0o777 == 0o555


def test_the_judge_checks_the_clean_copy_in_isolated_mode(og):
    run = og.checks / "runs" / "r1"
    argv = og.judge_argv(run, 0)
    assert argv[1:4] == ["-I", "-B", str(og.skill / "judge.py")]
    assert argv[argv.index("--harness-root") + 1] == str(run / "harness")
    assert argv[argv.index("--pins") + 1] == str(og.skill / "pins.json")


def test_a_pinned_file_that_changed_cannot_be_judged_and_runs_nothing(og):
    (og.checks / "harness" / "owner_gate" / "pairs.py").write_text("PAIRS = ('skip follow_mid',)\n")
    result = og.gate(SHA, IMAGE)
    assert result.code == og.CANNOT_JUDGE and "owner_gate/pairs.py" in result.record["reason"]
    assert not [c for c in og.calls if c[0] == "run"]


def test_a_pinned_file_that_is_a_symlink_cannot_be_judged(og, tmp_path):
    entry = og.checks / "harness" / "entry.py"
    (tmp_path / "elsewhere.py").write_bytes(entry.read_bytes())
    entry.unlink()
    entry.symlink_to(tmp_path / "elsewhere.py")
    result = og.gate(SHA, IMAGE)
    assert result.code == og.CANNOT_JUDGE and "entry.py" in result.record["reason"]
    assert not [c for c in og.calls if c[0] == "run"]


def test_no_pins_cannot_be_judged(og):
    (og.skill / "pins.json").write_text('{"files": {}}')
    result = og.gate(SHA, IMAGE)
    assert result.code == og.CANNOT_JUDGE and "pins" in result.record["reason"]
    assert not [c for c in og.calls if c[0] == "run"]


def test_old_run_folders_are_pruned(og, monkeypatch):
    monkeypatch.setattr(og, "KEEP_RUNS", 2)
    for minute in range(4):
        monkeypatch.setattr(og, "now", lambda m=minute: datetime(2026, 1, 7, 18, m, tzinfo=UTC))
        og.gate(SHA, IMAGE)
    assert len(list((og.checks / "runs").iterdir())) == 2 and len(records(og)) == 4
