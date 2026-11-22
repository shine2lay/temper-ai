#!/usr/bin/env python3
"""RollCall's owner-action gate for one release candidate (RollCall #59/#61; COO rm-1e7b442e).

    rollcall_owner_gate.py run --sha S --image IMAGE
        Runs the gate on IMAGE (which must be built at S) and prints its record. Exit 0 pass, 1 block,
        2 cannot judge. rollcall_cd_deploy.deploy() calls gate() for --kind deploy, after staging is green
        and before prod; a 1 or 2 there stops the release with prod untouched.

What one run does (contract: ~/rollcall-checks/owner-actions/CONTRACT.md):
  1. snapshots: every corpus/fixed/*.json (each checked against corpus/MANIFEST.json) and the newest
     corpus/latest/*.json, linked into runs/<run_id>/snapshots/ (one folder, mounted read-only);
  2. the candidate image, by id, must say it was built at S (ROLLCALL_COMMIT);
  3. backend #263's harness in that image: `docker run --rm --network none --read-only` with no env file and
     no keys (CONTRACT §4); its results stay in the run folder;
  4. RollCall's judge, allowed list and pins from RollCall's role folder (never a builder's copy; the
     builders' read-only copy in corpus/../judge must be byte-identical, or the gate cannot judge);
  5. one record {tried, refused, blocked, not_exercisable, ms, ...} appended to runs.jsonl (append only)
     and, when wt deploy names a notes file (DEPLOY_RECORD_NOTES), written there for its deploys.jsonl.
Nothing here places, changes or cancels an order, reads a broker, or touches the live prod DB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CHECKS = Path(os.environ.get("ROLLCALL_OWNER_GATE_CHECKS", str(Path.home() / "rollcall-checks" / "owner-actions")))
SKILL = Path(os.environ.get("ROLLCALL_OWNER_GATE_SKILL", str(
    Path.home() / ".pi" / "agent" / "memory" / "identities" / "rollcall" / "skills" / "owner-action-gate")))
#: Files of the role folder that must equal the builders' read-only copy (CONTRACT §1).
MIRRORED = ("judge.py", "allowed.json")
HARNESS_CEILING_S = 20 * 60
JUDGE_CEILING_S = 5 * 60
#: A latest capture older than this many market days is still run; the record says so (no block).
STALE_MARKET_DAYS = 3
KEEP_RUNS = 30
NOTES_ENV = "DEPLOY_RECORD_NOTES"
PASS, BLOCK, CANNOT_JUDGE = 0, 1, 2
NY = ZoneInfo("America/New_York")


class CannotRun(RuntimeError):
    """The gate could not run or could not be trusted: the release stops (exit 2)."""


@dataclass
class Gate:
    code: int
    record: dict = field(default_factory=dict)

    @property
    def summary(self) -> str:
        r = self.record
        if self.code == PASS:
            return (f"owner-action gate passed: tried {r.get('tried')}, refused {r.get('refused')} (all allowed), "
                    f"not exercisable {r.get('not_exercisable')}, {r.get('ms')} ms")
        if self.code == BLOCK:
            items = "; ".join(f"{b['action']} on {b['item_id']} {b['why']} {b.get('code') or ''}".strip()
                              for b in r.get("blocked_items", [])[:5])
            return f"owner-action gate blocked {r.get('blocked')}: {items}"
        return f"owner-action gate cannot judge: {r.get('reason')}"


# ---------------------------------------------------------------- the outside world --
# Each is replaced by a fake in tests/test_epd/test_rollcall_owner_gate.py.

def docker(*args: str, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, timeout=timeout, check=False)


def run_judge(run: Path, harness_exit: int) -> int:
    argv = [sys.executable, str(SKILL / "judge.py"), "--snapshots", str(run / "snapshots"),
            "--results", str(run / "out" / "results.jsonl"), "--harness-exit", str(harness_exit),
            "--harness-root", str(CHECKS / "harness"), "--allowed", str(SKILL / "allowed.json"),
            "--pins", str(SKILL / "pins.json"), "--out", str(run / "verdict.json")]
    return subprocess.run(argv, capture_output=True, text=True, timeout=JUDGE_CEILING_S, check=False).returncode


def now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------------- the parts --

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_mirror() -> None:
    for name in MIRRORED:
        mine, theirs = SKILL / name, CHECKS / "judge" / name
        if not mine.is_file() or not theirs.is_file() or sha256(mine) != sha256(theirs):
            raise CannotRun(f"{name}: the builders' copy in {CHECKS / 'judge'} differs from RollCall's")


def market_days_between(start: date, end: date) -> int:
    """Weekdays after `start` up to and including `end` (exchange holidays not counted out)."""
    days, d = 0, start
    while d < end:
        d += timedelta(days=1)
        days += d.weekday() < 5
    return days


def pick_snapshots(run: Path) -> dict:
    """corpus/fixed/* (each as MANIFEST.json lists it) + the newest corpus/latest/*, linked into run/snapshots."""
    corpus = CHECKS / "corpus"
    try:
        manifest = json.loads((corpus / "MANIFEST.json").read_text())
    except (OSError, ValueError) as e:
        raise CannotRun(f"corpus MANIFEST.json unreadable: {e}") from e
    fixed = sorted((corpus / "fixed").glob("*.json"))
    if not fixed:
        raise CannotRun(f"no fixed snapshot in {corpus / 'fixed'}")
    latest_files = sorted((corpus / "latest").glob("*.json")) if (corpus / "latest").is_dir() else []
    latest = latest_files[-1] if latest_files else None
    dest = run / "snapshots"
    dest.mkdir(mode=0o700)
    for path in [*fixed, *([latest] if latest else [])]:
        if path in fixed and manifest.get(path.stem) != sha256(path):
            raise CannotRun(f"fixed snapshot {path.name} does not match corpus/MANIFEST.json")
        try:
            os.link(path, dest / path.name)
        except OSError:
            shutil.copy2(path, dest / path.name)
    info: dict = {"fixed": [p.stem for p in fixed], "latest": None}
    if latest:
        try:
            captured = datetime.fromisoformat(json.loads(latest.read_text())["captured_at"].replace("Z", "+00:00"))
        except (OSError, ValueError, KeyError) as e:
            raise CannotRun(f"latest snapshot {latest.name} has no readable captured_at: {e}") from e
        days = market_days_between(captured.astimezone(NY).date(), now().astimezone(NY).date())
        info["latest"] = {"snapshot": latest.stem, "captured_at": captured.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "market_days_old": days, "stale": days > STALE_MARKET_DAYS}
    return info


def image_at(image: str, sha: str) -> str:
    """The id of `image`, which must say it was built at `sha` (its ROLLCALL_COMMIT)."""
    r = docker("image", "inspect", image, "--format", "{{.Id}} {{json .Config.Env}}", timeout=60)
    if r.returncode != 0:
        raise CannotRun(f"image {image} not found: {r.stderr.strip()[:200]}")
    image_id, env_json = r.stdout.strip().split(" ", 1)
    env = dict(e.split("=", 1) for e in json.loads(env_json) if "=" in e)
    commit = env.get("ROLLCALL_COMMIT", "")
    if len(commit) < 7 or not sha.startswith(commit):
        raise CannotRun(f"image {image} was built at {commit or 'an unknown commit'}, not {sha[:12]}")
    return image_id


def run_harness(run: Path, image_id: str, label: str) -> int:
    """CONTRACT §4 in the candidate image, offline; its exit code (CEILING: killed, 124)."""
    out = run / "out"
    out.mkdir(mode=0o700)
    name = f"owner-gate-{run.name}"
    argv = ["run", "--rm", "--name", name, "--network", "none", "--read-only", "--tmpfs", "/tmp",
            "--user", f"{os.getuid()}:{os.getgid()}", "-e", f"OWNER_GATE_IMAGE={label}",
            "-v", f"{run / 'snapshots'}:/snapshots:ro", "-v", f"{CHECKS / 'harness'}:/harness:ro",
            "-v", f"{out}:/out", "--entrypoint", "python", image_id,
            "/harness/entry.py", "--snapshot-dir", "/snapshots", "--out", "/out/results.jsonl"]
    try:
        r = docker(*argv, timeout=HARNESS_CEILING_S)
    except subprocess.TimeoutExpired:
        docker("kill", name, timeout=60)
        (run / "harness.log").write_text(f"harness passed its {HARNESS_CEILING_S // 60}-minute ceiling\n")
        return 124
    (run / "harness.log").write_text(f"{r.stdout}\n{r.stderr}")
    return r.returncode


def prune_runs(runs: Path) -> None:
    for old in sorted(p for p in runs.iterdir() if p.is_dir())[:-KEEP_RUNS]:
        shutil.rmtree(old, ignore_errors=True)


def append_record(record: dict) -> None:
    log = CHECKS / "runs.jsonl"
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
    finally:
        os.close(fd)
    if notes := os.environ.get(NOTES_ENV):
        Path(notes).write_text(json.dumps({"owner_action_gate": record}) + "\n")


# ---------------------------------------------------------------------------- the gate --

def gate(sha: str, image: str) -> Gate:
    """One gate run of `image` (built at `sha`); always appends one record, never raises CannotRun."""
    started, t0 = now(), time.monotonic()
    runs = CHECKS / "runs"
    runs.mkdir(mode=0o700, parents=True, exist_ok=True)
    run = runs / f"{started.strftime('%Y%m%dT%H%M%SZ')}-{sha[:12]}"
    record: dict = {"ts": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "run_id": run.name, "sha": sha, "image": image}
    try:
        run.mkdir(mode=0o700)
        check_mirror()
        record["snapshots"] = pick_snapshots(run)
        record["image_id"] = image_at(image, sha)
        record["harness_exit"] = run_harness(run, record["image_id"], f"{image} ({record['image_id'][:19]})")
        code = run_judge(run, record["harness_exit"])
        try:
            verdict = json.loads((run / "verdict.json").read_text())
        except (OSError, ValueError) as e:
            raise CannotRun(f"judge exit {code} wrote no readable verdict: {e}") from e
        if code not in (PASS, BLOCK, CANNOT_JUDGE):
            raise CannotRun(f"judge exit {code}: {verdict.get('reason')}")
        record["judge_exit"] = code
        record.update({k: verdict.get(k) for k in ("verdict", "expected", "tried", "refused", "allowed_refusals",
                                                   "blocked", "not_exercisable", "extra", "reason")})
        record["blocked_items"] = verdict.get("blocked_items") or []
    except (CannotRun, OSError, subprocess.SubprocessError) as e:
        code = CANNOT_JUDGE
        record.update(judge_exit=None, verdict="cannot_judge", reason=str(e))
    record["code"] = code
    record["ms"] = int((time.monotonic() - t0) * 1000)
    append_record({k: v for k, v in record.items() if v is not None or k == "judge_exit"})
    prune_runs(runs)
    return Gate(code, record)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the gate on one candidate image")
    r.add_argument("--sha", required=True)
    r.add_argument("--image", required=True)
    a = ap.parse_args(argv)
    result = gate(a.sha, a.image)
    print(json.dumps(result.record, indent=2, sort_keys=True))
    print(result.summary)
    return result.code


if __name__ == "__main__":
    sys.exit(main())
