"""Stage tests for scripts/test_slot.py: the commit hook's test phase waits for room on the machine.

Systems #18, H-GATE-ADMIT-1; docs/test-slots.md has the protocol. Each case has a known answer:
- idle 20 cores -> 8 workers at once; idle 9 -> 7
- idle 3 -> it waits, and is admitted when the 3rd measurement frees cores (waited_s recorded)
- never free -> after the longest wait it runs anyway with 4 workers, and says so loudly
- only the CPUs it may run on count; iowait counts as idle
- the cap, with real processes: a 3rd caller waits behind 2 held slots; SIGKILL frees a slot at once
- a background grandchild that outlives the wrapper holds no slot
- the ramp holds the line while the admitted command starts, and lets go when the command exits
- the exit code passes through; {workers} is replaced; no {workers} -> exit 2, nothing run
- INT and TERM stop the command too; a stop while waiting runs nothing
- its own faults (no /proc/stat, a directory it can't use, a lock error, a bad setting, a bug)
  -> the command runs unadmitted, saying why; TEST_SLOTS_MAX=0 -> off
- the log line has exactly the decided fields and nothing else, and rotates at 5 MB
- status is read-only
- the hook: bash -n passes, and its pytest call goes through test_slot.py as decided

In-process cases get a fake /proc/stat and a fake clock (FakeMachine). The cases with real
processes run main() on a stand-in machine that is all idle or all busy (RUNNER). Every slot
directory and log is a temporary one: the real ones are never touched.
"""

from __future__ import annotations

import errno
import fcntl
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "test_slot.py"
HOOK = ROOT / "scripts" / "git-hooks" / "pre-commit"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("test_slot_under_test", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


ts = _load()
MachineBase: Any = ts.Machine

# The fields decided for the log line (Systems #18), in order. Written out here rather than taken
# from the script, so a field added or dropped there shows up as a failure here.
DECIDED_FIELDS = [
    "v", "start", "end", "cwd", "label", "slot", "cap", "cores_allowed", "free_cores", "reserve",
    "workers", "waited_s", "ran_anyway", "unadmitted", "exit", "wall_s", "load1_start",
    "load1_end", "cpu_some_pct", "cgroup", "cgroup_cpu_some_pct",
]
BASE = datetime(2026, 10, 19, 22, 0, tzinfo=UTC)
# Writes the arguments after the file name into the file, as JSON.
RECORD = "import json, sys; open(sys.argv[1], 'w').write(json.dumps(sys.argv[2:]))"
# Writes its pid, then sleeps (exec keeps the pid, so the pid is the sleep's).
HOLD = 'echo $$ > "$0"; exec sleep 60'


# ─── A fake machine ───────────────────────────────────────────────────────


class FakeMachine(MachineBase):
    """A fake /proc/stat and a fake clock.

    ``plan`` says how idle the CPUs are during each measurement, in order (the last one repeats):
    a number N (the first N allowed CPUs idle, the rest busy) or {cpu: (idle, iowait)} as
    fractions of the time, with the CPUs left out busy."""

    def __init__(self, plan: list[Any], cpus: Iterable[int] | None = None, ncpu: int = 20) -> None:
        self.plan = plan
        self.allowed = set(range(ncpu) if cpus is None else cpus)
        self.ticks = {cpu: [0] * 8 for cpu in range(ncpu)}
        self.t = 0.0
        self.stat_reads = 0
        self.measurements = 0
        self.current: dict[int, tuple[float, float]] = {}
        self.stat_missing = False

    def _profile(self, k: int) -> dict[int, tuple[float, float]]:
        step = self.plan[min(k, len(self.plan) - 1)]
        if isinstance(step, dict):
            return step
        return {cpu: (1.0, 0.0) for cpu in sorted(self.allowed)[:step]}

    def proc_stat(self) -> str:
        if self.stat_missing:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", "/proc/stat")
        if self.stat_reads % 2 == 0:  # a measurement reads it twice, a window apart
            self.current = self._profile(self.stat_reads // 2)
            self.measurements += 1
        self.stat_reads += 1
        total = [sum(v[i] for v in self.ticks.values()) for i in range(8)]
        lines = ["cpu  " + " ".join(map(str, total)) + " 0 0"]
        lines += [f"cpu{cpu} " + " ".join(map(str, v)) + " 0 0" for cpu, v in sorted(self.ticks.items())]
        lines += ["intr 12345 0 0", "ctxt 678", "btime 1760000000", "processes 99"]
        return "\n".join(lines) + "\n"

    def affinity(self) -> set[int]:
        return set(self.allowed)

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        step = round(100 * seconds)  # USER_HZ
        for cpu, v in self.ticks.items():
            idle, iowait = self.current.get(cpu, (0.0, 0.0))
            i, w = round(step * idle), round(step * iowait)
            v[3] += i
            v[4] += w
            v[0] += step - i - w
        self.t += seconds

    def now(self) -> datetime:
        return BASE + timedelta(seconds=self.t)

    def load1(self) -> float | None:
        return 3.25

    def cpu_pressure(self) -> int | None:
        return None

    def cgroup(self) -> str | None:
        return "/user.slice/test.scope"

    def cgroup_pressure(self, cgroup: str) -> int | None:
        return None


def env_for(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {"HOME": str(tmp_path / "home"), "TEST_SLOTS_DIR": str(tmp_path / "slots"),
           "TEST_SLOTS_LOG": str(tmp_path / "log" / "runs.jsonl")}
    env.update(extra)
    return env


def run_main(tmp_path: Path, fake: FakeMachine, *options: str, command: list[str] | None = None,
             settings: dict[str, str] | None = None, **extra: str) -> int:
    """``test_slot.py run <options> -- <command>`` in-process, on the fake machine. The default
    command records its worker count in tmp_path/argv.json."""
    if command is None:
        command = [sys.executable, "-c", RECORD, str(tmp_path / "argv.json"), "{workers}"]
    env = env_for(tmp_path, **(settings or {}), **extra)
    return int(ts.main(["run", *options, "--", *command], env=env, machine=fake,
                       run_user=tmp_path / "no-run-user"))


def recorded(tmp_path: Path) -> list[str]:
    return list(json.loads((tmp_path / "argv.json").read_text()))


def log_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def only_row(tmp_path: Path) -> dict[str, Any]:
    rows = log_rows(tmp_path / "log" / "runs.jsonl")
    assert len(rows) == 1, rows
    return rows[0]


def held(slots_dir: Path, cap: int = 3) -> list[dict[str, Any]]:
    slots, _ = ts.read_holders(slots_dir, cap, ts.Machine())
    return [s for s in slots if s["held"]]


def wait_until(check: Callable[[], Any], what: str, timeout: float = 15.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie is dead for this purpose: it runs nothing and holds nothing.
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


# ─── Admission, on the fake machine ───────────────────────────────────────


@pytest.mark.parametrize(("idle", "workers"), [(20, 8), (9, 7)])
def test_a_machine_with_room_admits_at_once_with_workers_for_the_free_cores(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], idle: int, workers: int) -> None:
    fake = FakeMachine([idle])
    assert run_main(tmp_path, fake, "--label", "t", "--min-workers", "4", "--max-workers", "8") == 0
    assert recorded(tmp_path) == [str(workers)]
    assert fake.measurements == 1
    row = only_row(tmp_path)
    assert (row["workers"], row["free_cores"], row["slot"], row["waited_s"]) == (
        workers, idle - 2, 0, 3.0)
    assert row["ran_anyway"] is False and row["unadmitted"] is None
    err = capsys.readouterr().err
    assert (f"test-slot: admitted 't' with {workers} workers: free cores {idle - 2:.1f} of 20 "
            "(reserve 2), slot 0 of 3, after 0m03s") in err
    assert "waiting" not in err


def test_a_busy_machine_waits_and_is_admitted_when_the_third_measurement_frees_cores(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeMachine([3, 3, 20])
    assert run_main(tmp_path, fake, "--label", "t", "--min-workers", "4", "--max-workers", "8") == 0
    assert recorded(tmp_path) == ["8"]
    assert fake.measurements == 3
    # Measured at 0 s, 15 s and 30 s, each over a 3 s window.
    row = only_row(tmp_path)
    assert (row["waited_s"], row["workers"], row["free_cores"]) == (33.0, 8, 18.0)
    err = capsys.readouterr().err
    waits = [line for line in err.splitlines() if "waiting" in line]
    assert waits == [
        "test-slot: waiting for room (0m03s so far): free cores 1.0 of 20 (reserve 2, need 4); "
        f"slots 1/3 taken: [0] this phase, waiting for room since 22:00:00, in {os.getcwd()}"]
    assert ("admitted 't' with 8 workers: free cores 18.0 of 20 (reserve 2), slot 0 of 3, "
            "after 0m33s") in err


def test_a_machine_never_free_runs_anyway_after_the_longest_wait_with_the_fewest_workers(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeMachine([3])
    fails = "import sys; open(sys.argv[1], 'w').write(sys.argv[2]); sys.exit(1)"
    rc = run_main(tmp_path, fake, "--min-workers", "4", "--max-workers", "8",
                  command=[sys.executable, "-c", fails, str(tmp_path / "workers"), "{workers}"])
    assert rc == 1
    assert (tmp_path / "workers").read_text() == "4"
    row = only_row(tmp_path)
    assert (row["ran_anyway"], row["workers"], row["waited_s"], row["exit"], row["slot"]) == (
        True, 4, 1200.0, 1, 0)
    assert row["unadmitted"] is None
    lines = capsys.readouterr().err.splitlines()
    # A line when the wait begins, then one a minute.
    progress = [line for line in lines if "waiting for room (" in line]
    assert len(progress) == 20 and all("need 4" in line for line in progress)
    assert any("WARNING: still no room after 20m00s" in line
               and "Running ANYWAY with 4 workers" in line for line in lines)
    # It failed, so the last line says it ran on a busy machine.
    assert "these tests ran on a still-busy machine" in lines[-1]


def test_only_the_cpus_it_may_run_on_count_and_iowait_counts_as_idle(tmp_path: Path) -> None:
    others = {cpu: (1.0, 0.0) for cpu in [*range(10), *range(15, 20)]}
    mine = {10: (1.0, 0.0), 11: (1.0, 0.0), 12: (0.0, 1.0), 13: (0.5, 0.5), 14: (0.0, 0.0)}
    fake = FakeMachine([{**others, **mine}], cpus=range(10, 15))
    assert run_main(tmp_path, fake, "--min-workers", "2", "--max-workers", "8",
                    TEST_SLOTS_RESERVE="0") == 0
    assert recorded(tmp_path) == ["4"]
    row = only_row(tmp_path)
    assert (row["cores_allowed"], row["free_cores"], row["reserve"]) == (5, 4.0, 0)


def test_the_exit_code_passes_through_and_every_workers_is_replaced(tmp_path: Path) -> None:
    code = ("import json, sys; open(sys.argv[1], 'w').write(json.dumps(sys.argv[2:])); "
            "sys.exit(7)")
    rc = run_main(tmp_path, FakeMachine([20]), command=[
        sys.executable, "-c", code, str(tmp_path / "argv.json"), "-n", "{workers}",
        "--dist={workers}x"])
    assert rc == 7
    assert recorded(tmp_path) == ["-n", "8", "--dist=8x"]
    assert only_row(tmp_path)["exit"] == 7


def test_a_command_without_workers_is_refused_and_nothing_runs(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeMachine([20])
    marker = tmp_path / "ran"
    rc = run_main(tmp_path, fake, command=[sys.executable, "-c", f"open({str(marker)!r}, 'w')"])
    assert rc == 2
    assert "has no {workers}" in capsys.readouterr().err
    assert not marker.exists() and fake.measurements == 0
    assert not (tmp_path / "log").exists() and not (tmp_path / "slots").exists()


def test_admission_is_off_with_test_slots_max_0(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeMachine([0])
    assert run_main(tmp_path, fake, TEST_SLOTS_MAX="0") == 0
    assert recorded(tmp_path) == ["8"]
    err = capsys.readouterr().err
    assert "running unadmitted with 8 workers: admission is off (TEST_SLOTS_MAX=0)" in err
    assert fake.measurements == 0 and not (tmp_path / "slots").exists()
    row = only_row(tmp_path)
    assert (row["cap"], row["slot"], row["unadmitted"]) == (
        0, None, "admission is off (TEST_SLOTS_MAX=0)")


def _no_proc_stat(tmp_path: Path, fake: FakeMachine, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    fake.stat_missing = True
    return {}


def _unusable_dir(tmp_path: Path, fake: FakeMachine, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    (tmp_path / "a-file").write_text("")
    return {"TEST_SLOTS_DIR": str(tmp_path / "a-file" / "slots")}


def _lock_error(tmp_path: Path, fake: FakeMachine, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    def no_locks(fd: int) -> bool:
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(ts, "_try_flock", no_locks)
    return {}


def _bad_setting(tmp_path: Path, fake: FakeMachine, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    return {"TEST_SLOTS_MAX": "three"}


def _a_bug(tmp_path: Path, fake: FakeMachine, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    def broken(*args: Any) -> float:
        raise RuntimeError("boom")

    monkeypatch.setattr(ts, "measure", broken)
    return {}


@pytest.mark.parametrize(("fault", "reason"), [
    (_no_proc_stat, "FileNotFoundError: [Errno 2] No such file or directory: '/proc/stat'"),
    (_unusable_dir, "can't use the slot directory "),
    (_lock_error, "OSError: [Errno 37] No locks available"),
    (_bad_setting, "TEST_SLOTS_MAX='three' is not a whole number"),
    (_a_bug, "internal error: RuntimeError: boom"),
])
def test_its_own_fault_runs_the_command_unadmitted_saying_why(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
        fault: Callable[..., dict[str, str]], reason: str) -> None:
    fake = FakeMachine([20])
    assert run_main(tmp_path, fake, settings=fault(tmp_path, fake, monkeypatch)) == 0
    assert recorded(tmp_path) == ["8"]
    assert f"test-slot: running unadmitted with 8 workers: {reason}" in capsys.readouterr().err
    row = only_row(tmp_path)
    assert row["unadmitted"].startswith(reason) and row["slot"] is None and row["workers"] == 8
    if (tmp_path / "slots").is_dir():
        assert held(tmp_path / "slots") == []


# ─── The log ──────────────────────────────────────────────────────────────


def test_the_log_line_has_exactly_the_decided_fields_and_no_environment_or_arguments(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSTEMS18_CANARY", "env-value-that-must-not-be-logged")
    command = [sys.executable, "-c", RECORD, str(tmp_path / "argv.json"), "{workers}",
               "--arg-that-must-not-be-logged"]
    assert run_main(tmp_path, FakeMachine([20]), "--label", "temper-ai pytest",
                    command=command, SYSTEMS18_CANARY="settings-value-not-logged") == 0
    log = tmp_path / "log" / "runs.jsonl"
    text = log.read_text()
    assert "must-not-be-logged" not in text and "not-logged" not in text
    assert sys.executable not in text and "argv.json" not in text
    row = only_row(tmp_path)
    assert list(row) == DECIDED_FIELDS
    assert row["v"] == 1 and row["label"] == "temper-ai pytest" and row["cwd"] == os.getcwd()
    assert (row["cap"], row["reserve"], row["cores_allowed"], row["exit"]) == (3, 2, 20, 0)
    assert (row["load1_start"], row["load1_end"]) == (3.25, 3.25)
    assert row["cgroup"] == "/user.slice/test.scope"
    assert datetime.fromisoformat(row["start"]) == BASE + timedelta(seconds=3)
    assert datetime.fromisoformat(row["end"]).tzinfo is not None
    # Private: only its owner reads it.
    assert log.stat().st_mode & 0o777 == 0o600 and log.parent.stat().st_mode & 0o777 == 0o700


def test_the_log_records_cpu_pressure_over_the_run_machine_wide_and_for_its_cgroup(
        tmp_path: Path) -> None:
    assert ts.psi_some_total("some avg10=49.60 avg60=40.00 avg300=30.00 total=123456789\n"
                             "full avg10=0.00 avg60=0.00 avg300=0.00 total=5\n") == 123456789
    assert ts.psi_some_total(None) is None
    settings, problems = ts.read_settings(env_for(tmp_path), tmp_path / "no-run-user")
    assert problems == []
    fake = FakeMachine([20])
    run = ts.Run(settings, [], fake, "t", 4, "8", lambda line: None)
    outcome = ts.Outcome(cores=20, free=18.0, workers=8, slot=1, waited_s=3.0)
    ts.write_log(settings, lambda line: None, run, outcome, BASE, BASE + timedelta(seconds=10),
                 10.0, 0, "/app.slice/land.service",
                 ts.Pressure(1.5, 1_000_000, 0), ts.Pressure(2.5, 6_000_000, 2_000_000))
    row = only_row(tmp_path)
    assert (row["cpu_some_pct"], row["cgroup_cpu_some_pct"], row["cgroup"]) == (
        50.0, 20.0, "/app.slice/land.service")
    assert (row["load1_start"], row["load1_end"], row["wall_s"]) == (1.5, 2.5, 10.0)


def test_the_log_rotates_to_one_dot_1_file_at_5_mb(tmp_path: Path) -> None:
    assert ts.LOG_ROTATE_BYTES == 5 * 1024 * 1024
    log = tmp_path / "runs.jsonl"
    log.write_bytes(b"x" * (ts.LOG_ROTATE_BYTES - 1))
    ts.append_log(log, {"n": 1})  # under 5 MB: appended
    assert log.read_bytes().endswith(b'{"n": 1}\n') and not (tmp_path / "runs.jsonl.1").exists()
    size = log.stat().st_size
    ts.append_log(log, {"n": 2})  # at 5 MB: rotated first
    assert (tmp_path / "runs.jsonl.1").stat().st_size == size
    assert log.read_text() == '{"n": 2}\n'
    log.write_bytes(b"y" * ts.LOG_ROTATE_BYTES)
    ts.append_log(log, {"n": 3})  # one .1 file, replaced; never a .2
    assert (tmp_path / "runs.jsonl.1").read_bytes() == b"y" * ts.LOG_ROTATE_BYTES
    assert sorted(p.name for p in tmp_path.iterdir()) == ["runs.jsonl", "runs.jsonl.1"]


# ─── Settings and status ──────────────────────────────────────────────────


def test_the_defaults_are_the_decided_ones(tmp_path: Path) -> None:
    run_user = tmp_path / "run-user"
    settings, problems = ts.read_settings({"HOME": str(tmp_path)}, run_user)
    assert problems == []
    assert (settings.cap, settings.reserve, settings.wait_s, settings.window_s, settings.recheck_s,
            settings.ramp_s, settings.progress_s) == (3, 2, 1200, 3, 15, 30, 60)
    assert settings.slots_dir == tmp_path / ".cache" / "test-slots"
    assert settings.log == tmp_path / ".local" / "state" / "test-slots" / "runs.jsonl"
    run_user.mkdir()
    settings, _ = ts.read_settings({"HOME": str(tmp_path)}, run_user)
    assert settings.slots_dir == run_user / "test-slots"
    settings, problems = ts.read_settings(
        {"HOME": str(tmp_path), "TEST_SLOTS_MAX": "2", "TEST_SLOTS_RESERVE": "0",
         "TEST_SLOTS_WAIT_MINUTES": "0.5", "TEST_SLOTS_DIR": str(tmp_path / "s"),
         "TEST_SLOTS_LOG": str(tmp_path / "l.jsonl"), "TEST_SLOTS_RAMP_SECONDS": "0"}, run_user)
    assert problems == []
    assert (settings.cap, settings.reserve, settings.wait_s, settings.slots_dir, settings.log,
            settings.ramp_s) == (2, 0, 30, tmp_path / "s", tmp_path / "l.jsonl", 0)


def _snapshot(directory: Path) -> dict[str, tuple[int, bytes]]:
    return {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(directory.iterdir())}


def test_status_shows_who_holds_the_slots_and_changes_nothing(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    slots = tmp_path / "slots"
    slots.mkdir()
    (slots / "slot-0.lock").write_text(json.dumps({"pid": 999999, "label": "gone"}))  # not locked
    (slots / "admit.lock").write_text("")
    fd = os.open(slots / "slot-1.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, json.dumps({"pid": os.getpid(), "cwd": "/w/x", "label": "temper-ai pytest",
                                 "since": "2026-10-19T22:00:00-07:00", "workers": 6,
                                 "state": "running"}).encode())
        before = _snapshot(slots)
        env = env_for(tmp_path)
        assert ts.main(["status"], env=env, machine=FakeMachine([20])) == 0
        out = capsys.readouterr().out
        assert ts.main(["status", "--json"], env=env, machine=FakeMachine([20])) == 0
        report = json.loads(capsys.readouterr().out)
        assert _snapshot(slots) == before
    finally:
        os.close(fd)
    assert "slot 0: free" in out and "slot 2: free" in out
    assert (f"slot 1: pid {os.getpid()}, temper-ai pytest, running 6 workers since "
            "2026-10-19T22:00:00-07:00, in /w/x") in out
    assert "being admitted: nobody" in out
    assert "free cores now: 18.0 of 20 (idle 20.0, reserve 2)" in out
    assert [s["held"] for s in report["slots"]] == [False, True, False]
    assert report["slots"][1]["pid"] == os.getpid() and report["free_cores"] == 18.0
    # A directory that isn't there stays not there.
    assert ts.main(["status"], env=env_for(tmp_path, TEST_SLOTS_DIR=str(tmp_path / "nope")),
                   machine=FakeMachine([20])) == 0
    assert not (tmp_path / "nope").exists()


# ─── Real processes, on a stand-in machine ────────────────────────────────

RUNNER = '''\
"""Runs scripts/test_slot.py's main() on a stand-in machine: every CPU it may use idle
(FAKE_IDLE=1, the default) or busy (FAKE_IDLE=0), whatever the real machine is doing."""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("test_slot_runner", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class StandIn(mod.Machine):
    reads = 0

    def proc_stat(self):
        StandIn.reads += 1
        ticks = 100 * StandIn.reads
        idle = ticks if os.environ.get("FAKE_IDLE", "1") == "1" else 0
        return "".join(f"cpu{c} {ticks - idle} 0 0 {idle} 0 0 0 0 0 0\\n"
                       for c in sorted(self.affinity()))


sys.exit(mod.main(sys.argv[2:], machine=StandIn()))
'''


class Procs:
    """Starts wrappers on the stand-in machine; kills whatever is left at the end."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.runner = tmp_path / "runner.py"
        self.runner.write_text(RUNNER)
        self.started: list[subprocess.Popen[bytes]] = []
        self.pidfiles: list[Path] = []

    def env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TEST_SLOTS_")}
        env.update(TEST_SLOTS_DIR=str(self.tmp / "slots"), TEST_SLOTS_LOG=str(self.tmp / "runs.jsonl"),
                   TEST_SLOTS_WINDOW_SECONDS="0.05", TEST_SLOTS_RECHECK_SECONDS="0.1",
                   TEST_SLOTS_PROGRESS_SECONDS="0.1", TEST_SLOTS_RAMP_SECONDS="0")
        env.update(extra)
        return env

    def argv(self, label: str, *command: str) -> list[str]:
        return [sys.executable, str(self.runner), str(SOURCE), "run", "--label", label,
                "--min-workers", "1", "--max-workers", "1", "--", *command]

    def start(self, label: str, *command: str, env: dict[str, str]) -> subprocess.Popen[bytes]:
        with open(self.tmp / f"{label}.out", "wb") as out:
            proc = subprocess.Popen(self.argv(label, *command), env=env, stdout=out,
                                    stderr=subprocess.STDOUT)
        self.started.append(proc)
        return proc

    def hold(self, label: str, env: dict[str, str]) -> tuple[subprocess.Popen[bytes], int]:
        """A wrapper whose command sleeps; returns it and the command's pid."""
        pidfile = self.tmp / f"{label}.pid"
        self.pidfiles.append(pidfile)
        proc = self.start(label, "sh", "-c", HOLD, str(pidfile), "{workers}", env=env)
        pid = wait_until(lambda: pidfile.exists() and pidfile.read_text().strip(),
                         f"{label}'s command to start")
        return proc, int(pid)

    def out(self, label: str) -> str:
        return (self.tmp / f"{label}.out").read_text(errors="replace")

    def close(self) -> None:
        for proc in self.started:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        for pidfile in self.pidfiles:
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass


@pytest.fixture
def procs(tmp_path: Path) -> Iterator[Procs]:
    p = Procs(tmp_path)
    try:
        yield p
    finally:
        p.close()


def test_a_third_caller_waits_behind_two_held_slots_and_sigkill_frees_a_slot_at_once(
        tmp_path: Path, procs: Procs) -> None:
    env = procs.env(TEST_SLOTS_MAX="2")
    slots = tmp_path / "slots"
    a, a_command = procs.hold("A", env)
    procs.hold("B", env)
    wait_until(lambda: len(held(slots, 2)) == 2, "A and B to hold both slots")
    c = procs.start("C", sys.executable, "-c", RECORD, str(tmp_path / "c.json"), "{workers}",
                    env=env)
    wait_until(lambda: "waiting for a slot" in procs.out("C"), "C to wait for a slot")
    assert "slots 2/2 taken" in procs.out("C")
    assert c.poll() is None and not (tmp_path / "c.json").exists()

    a.kill()
    a.wait(timeout=10)
    assert a.pid not in [s["pid"] for s in held(slots, 2)]  # its slot went with it
    assert c.wait(timeout=10) == 0
    assert json.loads((tmp_path / "c.json").read_text()) == ["1"]
    [c_row] = [row for row in log_rows(tmp_path / "runs.jsonl") if row["label"] == "C"]
    assert c_row["slot"] == 0
    # The slot was A's own: the command A started still runs, and holds none.
    assert alive(a_command)


def test_a_background_grandchild_that_outlives_the_wrapper_holds_no_slot(
        tmp_path: Path, procs: Procs) -> None:
    env = procs.env()
    pidfile = tmp_path / "grandchild.pid"
    procs.pidfiles.append(pidfile)
    leave_behind = 'sleep 60 </dev/null >/dev/null 2>&1 & echo $! > "$0"'
    first = subprocess.run(procs.argv("first", "sh", "-c", leave_behind, str(pidfile), "{workers}"),
                           env=env, capture_output=True, timeout=30)
    assert first.returncode == 0, first.stdout + first.stderr
    assert alive(int(pidfile.read_text()))
    assert held(tmp_path / "slots") == []
    assert ts.read_holders(tmp_path / "slots", 3, ts.Machine())[1] is None  # nobody admitting
    second = subprocess.run(procs.argv("second", sys.executable, "-c", "pass", "{workers}"),
                            env=env, capture_output=True, timeout=30)
    assert second.returncode == 0
    assert [row["slot"] for row in log_rows(tmp_path / "runs.jsonl")] == [0, 0]


def test_the_ramp_holds_the_line_while_the_command_runs_and_lets_go_when_it_exits(
        tmp_path: Path, procs: Procs) -> None:
    a, a_command = procs.hold("A", procs.env(TEST_SLOTS_RAMP_SECONDS="600"))
    b = procs.start("B", sys.executable, "-c", RECORD, str(tmp_path / "b.json"), "{workers}",
                    env=procs.env())
    wait_until(lambda: "'A' is being admitted (ramping)" in procs.out("B"),
               "B to wait in line behind A's ramp")
    assert "waiting in line" in procs.out("B")
    assert b.poll() is None and not (tmp_path / "b.json").exists()
    os.kill(a_command, signal.SIGTERM)  # A's command ends: its ramp ends with it
    assert a.wait(timeout=10) == 128 + signal.SIGTERM
    assert b.wait(timeout=10) == 0
    assert (tmp_path / "b.json").exists()


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_int_and_term_stop_the_command_too(procs: Procs, signum: int) -> None:
    wrapper, command = procs.hold("sig", procs.env())
    wrapper.send_signal(signum)
    assert wrapper.wait(timeout=15) == 128 + signum
    wait_until(lambda: not alive(command), "the command to stop")


def test_a_stop_while_waiting_runs_nothing_and_frees_the_slot(tmp_path: Path, procs: Procs) -> None:
    marker = tmp_path / "ran.json"
    waiter = procs.start("waiter", sys.executable, "-c", RECORD, str(marker), "{workers}",
                         env=procs.env(FAKE_IDLE="0"))
    wait_until(lambda: "waiting for room" in procs.out("waiter"), "the wrapper to wait for room")
    waiter.send_signal(signal.SIGTERM)
    assert waiter.wait(timeout=10) == 128 + signal.SIGTERM
    assert not marker.exists()
    assert "stopped by SIGTERM while waiting" in procs.out("waiter")
    [row] = log_rows(tmp_path / "runs.jsonl")
    assert (row["exit"], row["slot"], row["workers"], row["unadmitted"]) == (
        143, None, None, "stopped by SIGTERM while waiting")
    assert held(tmp_path / "slots") == []


def test_the_progress_lines_go_to_the_progress_fd(tmp_path: Path, procs: Procs) -> None:
    progress = tmp_path / "progress.txt"
    argv = procs.argv("p", sys.executable, "-c", "print('ran')", "{workers}")
    argv[argv.index("--"):argv.index("--")] = ["--progress-fd", "3"]
    done = subprocess.run(["bash", "-c", 'exec 3>"$0"; exec "$@"', str(progress), *argv],
                          env=procs.env(), capture_output=True, text=True, timeout=30)
    assert (done.returncode, done.stdout, done.stderr) == (0, "ran\n", "")
    assert "test-slot: admitted 'p' with 1 workers" in progress.read_text()


# ─── The hook ─────────────────────────────────────────────────────────────


def test_the_hook_parses_and_runs_pytest_through_test_slot_as_decided() -> None:
    assert subprocess.run(["bash", "-n", str(HOOK)]).returncode == 0
    text = HOOK.read_text()
    wiring = ('python3 scripts/test_slot.py run --label "temper-ai pytest" --min-workers 4 '
              '--max-workers "$PYTEST_WORKERS" --progress-fd 3 -- uv run --quiet pytest tests/ '
              '--timeout=120 -q --no-header -n {workers}')
    calls = [line for line in text.splitlines()
             if "pytest" in line and not line.lstrip().startswith(("#", "echo"))
             and "PYTEST_WORKERS=" not in line]
    assert len(calls) == 1, calls
    line = calls[0]
    assert line.index("unset $(git rev-parse --local-env-vars);") < line.index(wiring)
    assert line.index(wiring) < line.index(") 3>&2 2>&1 | tail -40")
    assert 'PYTEST_WORKERS="${PRECOMMIT_PYTEST_WORKERS:-8}"' in text
