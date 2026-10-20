#!/usr/bin/env python3
"""test_slot: start a test phase only when the machine has room for it.

    python3 scripts/test_slot.py run --label "temper-ai pytest" --min-workers 4 --max-workers 8 \\
        --progress-fd 3 -- uv run --quiet pytest tests/ -n {workers}
    python3 scripts/test_slot.py status [--json]

temper-ai's commit hook (scripts/git-hooks/pre-commit, which ``wt land`` also runs as the repo's
check) wraps its pytest call in ``run``. Before, the test phase started 8 xdist workers however
busy the machine was, and nothing capped how many phases ran at once: with the machine
oversubscribed at equal weight, the Team-run waits in tests/test_runner/pi_parking overran their
20 s and a land failed for the machine, not the change (Systems #18, H-GATE-ADMIT-1;
docs/test-slots.md).

The protocol
------------
1. Slots. At most TEST_SLOTS_MAX (3) admitted test phases run at once on the machine. Slot N is an
   exclusive flock on ``slot-N.lock`` in TEST_SLOTS_DIR. The lock files are opened close-on-exec
   and the command gets no other descriptor of ours, so a slot frees the moment its holder exits
   or is killed, and nothing the command starts can keep it.
2. One admission at a time. The phase being admitted holds ``admit.lock``; the others wait in line
   for it. Holding it, a phase takes a free slot (or waits for one), then measures the free cores:
   idle + iowait over a TEST_SLOTS_WINDOW_SECONDS (3 s) window of /proc/stat, summed over the CPUs
   this process may run on (sched_getaffinity), minus TEST_SLOTS_RESERVE (2). Its workers are
   min(--max-workers, floor(free cores)). It starts when that is at least --min-workers, and
   otherwise measures again every TEST_SLOTS_RECHECK_SECONDS (15 s). (--min-workers is never
   taken as more than --max-workers, or than the allowed cores minus the reserve.)
3. The ramp. After starting the command, the phase keeps admit.lock for TEST_SLOTS_RAMP_SECONDS
   (30 s), or until the command exits, so the next phase measures after this one's workers have
   taken their cores: two phases never count the same free cores.
4. Waiting. A line on --progress-fd says the free cores, who holds the slots and the wait so far:
   one when the wait begins, then every TEST_SLOTS_PROGRESS_SECONDS (60 s). After
   TEST_SLOTS_WAIT_MINUTES (20) it runs anyway with --min-workers and says so loudly; if the
   command then fails, it says again, as the last line of the command's output, that the command
   ran on a still-busy machine.
5. Off, and its own faults. TEST_SLOTS_MAX=0 turns admission off: the command runs at once with
   --max-workers, and it says so. A fault of its own (no /proc/stat, a slot directory it can't
   use, a lock error, a bad setting) is said and logged, and the command runs unadmitted with
   --max-workers: it never holds up a commit for its own fault. A --max-workers that is no
   worker count (``0``, say) goes into the command as given, unadmitted.
6. The command. Every ``{workers}`` in its arguments becomes the worker count; a command without
   one is refused (exit 2). It runs as a child in a process group of its own. INT, TERM and HUP
   are passed on to that group, and the group is killed if it is still there 10 s after the
   first. The exit code is the command's (128 + N when signal N ended it).
7. The log. One JSON line per run in TEST_SLOTS_LOG, with the fields in LOG_FIELDS; "start",
   "end", "wall_s", the loads and the CPU pressure are the command's run, "waited_s" the wait
   before it. No environment, no command arguments beyond the label. At 5 MB it rotates to one
   ``.1`` file.
8. ``status`` is read-only: the slots held (pid, cwd, label, since, workers), who is being
   admitted, and the free cores now. It tells a held slot from a free one by /proc/locks.

Settings (environment): TEST_SLOTS_MAX=3; TEST_SLOTS_DIR (/run/user/<uid>/test-slots when
/run/user/<uid> exists, else ~/.cache/test-slots); TEST_SLOTS_RESERVE=2; TEST_SLOTS_WAIT_MINUTES=20;
TEST_SLOTS_LOG (~/.local/state/test-slots/runs.jsonl); TEST_SLOTS_WINDOW_SECONDS=3;
TEST_SLOTS_RECHECK_SECONDS=15; TEST_SLOTS_RAMP_SECONDS=30; TEST_SLOTS_PROGRESS_SECONDS=60.

Standard library only. Linux: flock, /proc and process groups.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any, TextIO

LOG_VERSION = 1
LOG_FIELDS = (
    "v", "start", "end", "cwd", "label", "slot", "cap", "cores_allowed", "free_cores", "reserve",
    "workers", "waited_s", "ran_anyway", "unadmitted", "exit", "wall_s", "load1_start",
    "load1_end", "cpu_some_pct", "cgroup", "cgroup_cpu_some_pct",
)
LOG_ROTATE_BYTES = 5 * 1024 * 1024
KILL_GRACE_S = 10.0
POLL_S = 0.5
FORWARDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
SAY = "test-slot:"
Say = Callable[[str], None]


# ─── Settings ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Settings:
    cap: int
    slots_dir: Path
    reserve: float
    wait_s: float
    log: Path
    window_s: float
    recheck_s: float
    ramp_s: float
    progress_s: float


def _home(env: Mapping[str, str]) -> Path:
    return Path(env.get("HOME") or str(Path.home()))


def default_slots_dir(env: Mapping[str, str], run_user: Path) -> Path:
    """/run/user/<uid>/test-slots when /run/user/<uid> exists (a tmpfs: nothing outlives a
    reboot), else ~/.cache/test-slots."""
    if run_user.is_dir():
        return run_user / "test-slots"
    return _home(env) / ".cache" / "test-slots"


def read_settings(env: Mapping[str, str], run_user: Path | None = None) -> tuple[Settings, list[str]]:
    """The settings, and what was wrong with any of them (that one then keeps its default)."""
    problems: list[str] = []

    def number(name: str, default: float, low: float, *, whole: bool = False,
               above: bool = False) -> float:
        raw = env.get(name, "").strip()
        if not raw:
            return default
        try:
            value: float = int(raw) if whole else float(raw)
        except ValueError:
            problems.append(f"{name}={raw!r} is not a {'whole number' if whole else 'number'}")
            return default
        if not math.isfinite(value) or value < low or (above and value == low):
            problems.append(f"{name}={raw!r} is out of range")
            return default
        return value

    if run_user is None:
        run_user = Path(f"/run/user/{os.getuid()}")
    slots_dir = (Path(env["TEST_SLOTS_DIR"]).expanduser() if env.get("TEST_SLOTS_DIR")
                 else default_slots_dir(env, run_user))
    log = (Path(env["TEST_SLOTS_LOG"]).expanduser() if env.get("TEST_SLOTS_LOG")
           else _home(env) / ".local" / "state" / "test-slots" / "runs.jsonl")
    settings = Settings(
        cap=int(number("TEST_SLOTS_MAX", 3, 0, whole=True)),
        slots_dir=slots_dir,
        reserve=number("TEST_SLOTS_RESERVE", 2, 0),
        wait_s=60 * number("TEST_SLOTS_WAIT_MINUTES", 20, 0),
        log=log,
        window_s=number("TEST_SLOTS_WINDOW_SECONDS", 3, 0, above=True),
        recheck_s=number("TEST_SLOTS_RECHECK_SECONDS", 15, 0, above=True),
        ramp_s=number("TEST_SLOTS_RAMP_SECONDS", 30, 0),
        progress_s=number("TEST_SLOTS_PROGRESS_SECONDS", 60, 0, above=True),
    )
    return settings, problems


# ─── The machine ──────────────────────────────────────────────────────────


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def psi_some_total(text: str | None) -> int | None:
    """The "some" total (microseconds) of a cpu.pressure file."""
    for line in (text or "").splitlines():
        if line.startswith("some "):
            for part in line.split():
                if part.startswith("total="):
                    with contextlib.suppress(ValueError):
                        return int(part[len("total="):])
    return None


class Machine:
    """The machine as test_slot sees it: /proc, the CPUs it may use, the clock. The stage tests
    (tests/test_scripts/test_test_slot.py) put a fake one in its place."""

    def proc_stat(self) -> str:
        return Path("/proc/stat").read_text(encoding="ascii")

    def affinity(self) -> set[int]:
        return set(os.sched_getaffinity(0))

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def now(self) -> datetime:
        return datetime.now(UTC).astimezone()

    def load1(self) -> float | None:
        try:
            return float((_read("/proc/loadavg") or "").split()[0])
        except (IndexError, ValueError):
            return None

    def proc_locks(self) -> str | None:
        return _read("/proc/locks")

    def cpu_pressure(self) -> int | None:
        return psi_some_total(_read("/proc/pressure/cpu"))

    def cgroup(self) -> str | None:
        for line in (_read("/proc/self/cgroup") or "").splitlines():
            if line.startswith("0::"):
                return line[3:] or "/"
        return None

    def cgroup_pressure(self, cgroup: str) -> int | None:
        return psi_some_total(_read(f"/sys/fs/cgroup/{cgroup.strip('/')}/cpu.pressure"))


def cpu_ticks(stat: str) -> dict[int, tuple[int, int]]:
    """Per CPU: (idle + iowait ticks, all ticks), from /proc/stat's ``cpuN`` lines."""
    ticks: dict[int, tuple[int, int]] = {}
    for line in stat.splitlines():
        name, _, rest = line.partition(" ")
        if not (name.startswith("cpu") and name[3:].isdigit()):
            continue
        values = [int(v) for v in rest.split()[:8]]
        if len(values) < 4:
            raise ValueError(f"a short /proc/stat line: {line!r}")
        values += [0] * (8 - len(values))
        # user nice system idle iowait irq softirq steal (guest time is already in user and nice)
        ticks[int(name[3:])] = (values[3] + values[4], sum(values))
    if not ticks:
        raise ValueError("/proc/stat has no cpuN lines")
    return ticks


def idle_cores(before: Mapping[int, tuple[int, int]], after: Mapping[int, tuple[int, int]],
               cpus: set[int]) -> float:
    """How many of ``cpus`` were idle (or waiting on I/O) between two cpu_ticks readings."""
    idle = 0.0
    for cpu in cpus:
        if cpu in before and cpu in after:
            spent = after[cpu][1] - before[cpu][1]
            if spent > 0:
                idle += min(1.0, max(0.0, (after[cpu][0] - before[cpu][0]) / spent))
    return idle


def measure(machine: Machine, cpus: set[int], window_s: float) -> float:
    """Idle cores among ``cpus`` over one window. Raises OSError or ValueError."""
    before = cpu_ticks(machine.proc_stat())
    machine.sleep(window_s)
    return idle_cores(before, cpu_ticks(machine.proc_stat()), cpus)


# ─── Locks, and who holds them ────────────────────────────────────────────


def _open_lock(path: Path) -> int:
    return os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)


def _try_flock(fd: int) -> bool:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _write_info(fd: int, info: Mapping[str, Any] | None) -> None:
    """Say who holds a lock, in its file (``status`` reads it). Cosmetic: never fails."""
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
        if info is not None:
            os.pwrite(fd, json.dumps(info).encode(), 0)


def _read_info(path: Path) -> dict[str, Any]:
    try:
        info = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


class Held:
    """A lock this process holds (``fd`` is None once it has let go)."""

    def __init__(self, fd: int, slot: int | None = None) -> None:
        self.fd: int | None = fd
        self.slot = slot

    def note(self, info: Mapping[str, Any]) -> None:
        if self.fd is not None:
            _write_info(self.fd, info)

    def release(self) -> None:
        fd, self.fd = self.fd, None
        if fd is not None:
            _write_info(fd, None)
            with contextlib.suppress(OSError):
                os.close(fd)


def lock_table(text: str) -> list[tuple[int, int, int, int]]:
    """(major, minor, inode, pid) of each flock held, from /proc/locks (waiters skipped)."""
    table: list[tuple[int, int, int, int]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[1] != "FLOCK":
            continue
        try:
            major, minor, inode = parts[5].split(":")
            table.append((int(major, 16), int(minor, 16), int(inode), int(parts[4])))
        except ValueError:
            continue
    return table


def _holder(path: Path, table: list[tuple[int, int, int, int]] | None,
            info: Mapping[str, Any]) -> int | None:
    """The pid holding ``path``'s lock, or None when it is free."""
    try:
        st = path.stat()
    except OSError:
        return None
    pid_named = info.get("pid")
    claimed: int | None = pid_named if isinstance(pid_named, int) else None
    if table is None:  # no /proc/locks: go by the pid the file names, if it is alive
        if claimed is None:
            return None
        try:
            os.kill(claimed, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass
        return claimed
    dev = (os.major(st.st_dev), os.minor(st.st_dev))
    for major, minor, inode, pid in table:
        if inode == st.st_ino and (major, minor) == dev:
            return pid
    # Some filesystems (btrfs subvolumes) show stat() a device number /proc/locks doesn't use.
    for _, _, inode, pid in table:
        if inode == st.st_ino and pid == claimed:
            return pid
    return None


def read_holders(slots_dir: Path, cap: int,
                 machine: Machine) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Every slot (held or free), and who is being admitted. Read-only."""
    text = machine.proc_locks()
    table = lock_table(text) if text is not None else None
    numbers = set(range(cap))
    with contextlib.suppress(OSError):
        for path in slots_dir.glob("slot-*.lock"):
            with contextlib.suppress(ValueError):
                numbers.add(int(path.name[len("slot-"):-len(".lock")]))
    slots: list[dict[str, Any]] = []
    for n in sorted(numbers):
        path = slots_dir / f"slot-{n}.lock"
        info = _read_info(path)
        pid = _holder(path, table, info)
        row: dict[str, Any] = {"slot": n, "held": pid is not None}
        if pid is not None:
            row["pid"] = pid
            row.update({key: info.get(key) for key in ("cwd", "label", "since", "workers", "state")})
        slots.append(row)
    admit_path = slots_dir / "admit.lock"
    admit_info = _read_info(admit_path)
    admit_pid = _holder(admit_path, table, admit_info)
    admitting: dict[str, Any] | None = None
    if admit_pid is not None:
        admitting = {"pid": admit_pid}
        admitting.update({key: admit_info.get(key) for key in ("cwd", "label", "since", "state")})
    return slots, admitting


def _clock(iso: Any) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%H:%M:%S")
    except ValueError:
        return "?"


def describe_slots(slots: Sequence[Mapping[str, Any]], cap: int, me: int) -> str:
    held = [s for s in slots if s["held"]]
    if not held:
        return f"slots 0/{cap} taken"
    parts = []
    for s in held:
        who = "this phase" if s["pid"] == me else f"pid {s['pid']} {s.get('label') or '?'!r}"
        doing = (f"{s['workers']} workers" if s.get("state") == "running" and s.get("workers")
                 else "waiting for room")
        parts.append(f"[{s['slot']}] {who}, {doing} since {_clock(s.get('since'))}, "
                     f"in {s.get('cwd') or '?'}")
    return f"slots {len(held)}/{cap} taken: " + "; ".join(parts)


# ─── Waiting for room ─────────────────────────────────────────────────────


class _Stopped(BaseException):
    """A stop signal came while waiting, before the command started."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


class _Signals:
    """INT, TERM and HUP: while waiting they stop the wait; once the command runs they are passed
    on to its process group, which is killed if it is still there KILL_GRACE_S later."""

    def __init__(self) -> None:
        self.phase = "waiting"  # waiting | starting | running | done
        self.child: subprocess.Popen[bytes] | None = None
        self.pending: int | None = None
        self._killer: threading.Timer | None = None
        self._previous: dict[int, Any] = {}

    def install(self) -> None:
        for signum in FORWARDED:
            with contextlib.suppress(ValueError, OSError):  # ValueError: not the main thread
                self._previous[signum] = signal.signal(signum, self._handle)

    def restore(self) -> None:
        if self._killer is not None:
            self._killer.cancel()
        for signum, handler in self._previous.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signum, handler)

    def running(self, child: subprocess.Popen[bytes]) -> None:
        self.child, self.phase = child, "running"
        if self.pending is not None:
            self._forward(self.pending)

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        if self.phase == "waiting":
            raise _Stopped(signum)
        if self.phase == "starting":
            self.pending = self.pending or signum
        elif self.phase == "running":
            self._forward(signum)

    def _forward(self, signum: int) -> None:
        child = self.child
        if child is None:
            return
        with contextlib.suppress(OSError):
            os.killpg(child.pid, signum)
        if self._killer is None:
            self._killer = threading.Timer(KILL_GRACE_S, self._kill)
            self._killer.daemon = True
            self._killer.start()

    def _kill(self) -> None:
        child = self.child
        if child is not None and self.phase == "running":
            with contextlib.suppress(OSError):
                os.killpg(child.pid, signal.SIGKILL)


@dataclass
class Outcome:
    cores: int | None = None
    free: float | None = None
    workers: int | None = None
    verbatim: str | None = None  # a --max-workers that is no worker count, passed on as given
    slot: int | None = None
    waited_s: float = 0.0
    ran_anyway: bool = False
    unadmitted: str | None = None
    no_room: str = ""
    admit: Held | None = None
    slot_lock: Held | None = None
    held: list[Held] = field(default_factory=list)

    def let_go(self) -> None:
        for lock in self.held:
            lock.release()
        self.admit = self.slot_lock = None


def _dur(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}m{s % 60:02d}s"


def _num(x: float) -> float | int:
    return int(x) if float(x).is_integer() else round(x, 2)


def max_workers(text: str, cores: int) -> int | None:
    """--max-workers as a count: a whole number from 1, or auto/logical (the allowed cores)."""
    word = text.strip().lower()
    if word in ("auto", "logical"):
        return max(1, cores)
    try:
        value = int(word)
    except ValueError:
        return None
    return value if value >= 1 else None


class Run:
    """One ``run``: wait for room, then run the command and log it."""

    def __init__(self, settings: Settings, problems: Sequence[str], machine: Machine, label: str,
                 min_workers: int, max_text: str, say: Say) -> None:
        self.s = settings
        self.problems = list(problems)
        self.m = machine
        self.label = label
        self.min_workers = min_workers
        self.max_text = max_text
        self.say = say
        self.pid = os.getpid()
        self.cwd: str | None
        try:
            self.cwd = os.getcwd()
        except OSError:
            self.cwd = None

    def info(self, state: str, workers: int | None = None) -> dict[str, Any]:
        return {"pid": self.pid, "cwd": self.cwd, "label": self.label,
                "since": self.m.now().isoformat(timespec="seconds"), "workers": workers,
                "state": state}

    def admit(self, o: Outcome) -> None:
        """Wait for room. Returns with ``o.workers`` (or ``o.verbatim``) set: admitted, run
        anyway (``o.ran_anyway``) or unadmitted (``o.unadmitted`` says why)."""
        s, m = self.s, self.m
        cpus = m.affinity()
        cores = o.cores = len(cpus)
        top = max_workers(self.max_text, cores)
        if top is None:
            o.verbatim = self.max_text
            o.unadmitted = f"--max-workers {self.max_text!r} is no worker count; passed on as given"
            return
        o.workers = top
        if self.problems:
            o.unadmitted = "; ".join(self.problems)
            return
        if s.cap == 0:
            o.unadmitted = "admission is off (TEST_SLOTS_MAX=0)"
            return
        most = math.floor(cores - s.reserve + 1e-9)
        if most < 1:
            o.unadmitted = (f"only {cores} cores allowed, no more than the reserve "
                            f"(TEST_SLOTS_RESERVE={_num(s.reserve)})")
            return
        need = max(1, min(self.min_workers, top, most))
        try:
            s.slots_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            admit_lock = Held(_open_lock(s.slots_dir / "admit.lock"))
        except OSError as exc:
            o.unadmitted = f"can't use the slot directory {s.slots_dir}: {exc}"
            return
        o.held.append(admit_lock)
        start = m.monotonic()
        deadline = start + s.wait_s
        next_measure = start
        next_progress: float | None = None
        last_measured: float | None = None
        measured = False
        try:
            while True:
                now = m.monotonic()
                if o.admit is None and admit_lock.fd is not None and _try_flock(admit_lock.fd):
                    o.admit = admit_lock
                    admit_lock.note(self.info("waiting"))
                if o.admit is not None and o.slot_lock is None:
                    o.slot_lock = self._take_slot(o)
                ready = o.admit is not None and o.slot_lock is not None
                if now >= deadline and (measured or not ready):
                    break
                if ready and now >= next_measure:
                    next_measure = now + s.recheck_s
                    o.free = measure(m, cpus, s.window_s) - s.reserve
                    last_measured = m.monotonic()
                    measured = True
                    o.workers = max(0, min(top, math.floor(o.free + 1e-9)))
                    if o.workers >= need:
                        o.waited_s = m.monotonic() - start
                        o.slot = o.slot_lock.slot if o.slot_lock is not None else None
                        return
                    continue
                if next_progress is None or now >= next_progress:
                    if last_measured is None or now - last_measured >= s.recheck_s:
                        o.free = measure(m, cpus, s.window_s) - s.reserve
                        last_measured = now = m.monotonic()
                    self._progress(o, now - start, need)
                    next_progress = now + s.progress_s
                wake = next_measure if ready else now + min(POLL_S, s.recheck_s)
                m.sleep(max(0.0, min(wake, next_progress, deadline) - now))
        except (OSError, ValueError) as exc:
            o.let_go()
            o.waited_s = m.monotonic() - start
            o.free, o.workers = None, top
            o.unadmitted = f"{type(exc).__name__}: {exc}"
            return
        # No room in time: run anyway with the fewest workers, in a slot if one is free.
        o.waited_s = m.monotonic() - start
        o.ran_anyway = True
        o.workers = need
        if o.slot_lock is None:
            with contextlib.suppress(OSError):
                o.slot_lock = self._take_slot(o)
        o.slot = o.slot_lock.slot if o.slot_lock is not None else None
        free = f"{o.free:.1f}" if o.free is not None else "not measured"
        o.no_room = f"free cores {free} of {cores} after {_dur(o.waited_s)}, need {need}"
        self.say(f"{SAY} WARNING: still no room after {_dur(o.waited_s)} (free cores {free} of "
                 f"{cores}, reserve {_num(s.reserve)}, need {need}). Running ANYWAY with {need} "
                 f"workers on a busy machine: a timing failure in this run may be the machine, "
                 f"not the change.")

    def _take_slot(self, o: Outcome) -> Held | None:
        for n in range(self.s.cap):
            fd = _open_lock(self.s.slots_dir / f"slot-{n}.lock")
            if _try_flock(fd):
                lock = Held(fd, n)
                o.held.append(lock)
                lock.note(self.info("waiting"))
                return lock
            os.close(fd)
        return None

    def _progress(self, o: Outcome, waited: float, need: int) -> None:
        s = self.s
        slots, admitting = read_holders(s.slots_dir, s.cap, self.m)
        free = f"{o.free:.1f}" if o.free is not None else "?"
        cores = f"free cores {free} of {o.cores} (reserve {_num(s.reserve)}, need {need})"
        taken = describe_slots(slots, s.cap, self.pid)
        if o.admit is None:
            who = "another phase is being admitted"
            if admitting is not None:
                who = (f"pid {admitting['pid']} {admitting.get('label') or '?'!r} is being admitted "
                       f"({admitting.get('state') or '?'})")
            self.say(f"{SAY} waiting in line ({_dur(waited)} so far): {who}; {cores}; {taken}")
        elif o.slot_lock is None:
            self.say(f"{SAY} waiting for a slot ({_dur(waited)} so far): {taken}; {cores}")
        else:
            self.say(f"{SAY} waiting for room ({_dur(waited)} so far): {cores}; {taken}")


# ─── Running the command, and the log ─────────────────────────────────────


def append_log(path: Path, row: Mapping[str, Any]) -> None:
    """One line at the end of the log, rotating it to ``.1`` once it has reached 5 MB."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = (json.dumps(row) + "\n").encode()
    for _ in range(5):
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            st = os.fstat(fd)
            try:
                current = os.stat(path).st_ino == st.st_ino
            except FileNotFoundError:
                current = False
            if not current:  # rotated while this one waited for the lock: write to the new one
                continue
            if st.st_size >= LOG_ROTATE_BYTES:
                os.replace(path, path.with_name(path.name + ".1"))
                continue
            os.write(fd, line)
            return
        finally:
            os.close(fd)
    raise OSError(f"{path} kept moving")


def _pct(before: int | None, after: int | None, wall_s: float) -> float | None:
    if before is None or after is None or wall_s <= 0:
        return None
    return round(100.0 * (after - before) / (wall_s * 1e6), 1)


@dataclass
class Pressure:
    load1: float | None
    psi: int | None
    cgroup_psi: int | None


def _pressure(m: Machine, cgroup: str | None) -> Pressure:
    return Pressure(m.load1(), m.cpu_pressure(), m.cgroup_pressure(cgroup) if cgroup else None)


def write_log(settings: Settings, say: Say, r: Run, o: Outcome, start: datetime, end: datetime,
              wall: float, rc: int, cgroup: str | None, before: Pressure | None,
              after: Pressure | None) -> None:
    row = {
        "v": LOG_VERSION,
        "start": start.isoformat(timespec="milliseconds"),
        "end": end.isoformat(timespec="milliseconds"),
        "cwd": r.cwd,
        "label": r.label,
        "slot": o.slot,
        "cap": settings.cap,
        "cores_allowed": o.cores,
        "free_cores": round(o.free, 2) if o.free is not None else None,
        "reserve": _num(settings.reserve),
        "workers": o.workers if o.verbatim is None else None,
        "waited_s": round(o.waited_s, 1),
        "ran_anyway": o.ran_anyway,
        "unadmitted": o.unadmitted,
        "exit": rc,
        "wall_s": round(wall, 1),
        "load1_start": before.load1 if before else None,
        "load1_end": after.load1 if after else None,
        "cpu_some_pct": _pct(before.psi, after.psi, wall) if before and after else None,
        "cgroup": cgroup,
        "cgroup_cpu_some_pct": (_pct(before.cgroup_psi, after.cgroup_psi, wall)
                                if before and after else None),
    }
    try:
        append_log(settings.log, row)
    except OSError as exc:
        say(f"{SAY} couldn't write the log {settings.log}: {exc}")


def _launch(command: list[str], settings: Settings, m: Machine, say: Say, signals: _Signals,
            r: Run, o: Outcome) -> int:
    value = o.verbatim if o.verbatim is not None else str(o.workers)
    if o.unadmitted is not None:
        say(f"{SAY} running unadmitted with {value} workers: {o.unadmitted}")
    elif not o.ran_anyway:
        say(f"{SAY} admitted {r.label!r} with {value} workers: free cores {o.free:.1f} of "
            f"{o.cores} (reserve {_num(settings.reserve)}), slot {o.slot} of {settings.cap}, "
            f"after {_dur(o.waited_s)}")
    argv = [arg.replace("{workers}", value) for arg in command]
    cgroup = m.cgroup()
    before = _pressure(m, cgroup)
    start, t0 = m.now(), m.monotonic()
    if o.slot_lock is not None:
        o.slot_lock.note(r.info("running", o.workers))
    if o.admit is not None:
        o.admit.note(r.info("ramping", o.workers))
    signals.phase = "starting"
    try:
        child = subprocess.Popen(argv, process_group=0)
    except OSError as exc:
        signals.phase = "done"
        rc = 127 if isinstance(exc, FileNotFoundError) else 126
        say(f"{SAY} couldn't start {argv[0]!r}: {exc}")
        write_log(settings, say, r, o, start, m.now(), 0.0, rc, cgroup, None, None)
        return rc
    signals.running(child)
    if o.admit is not None:
        if settings.ramp_s > 0:
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=settings.ramp_s)
        o.admit.release()
    child.wait()
    signals.phase = "done"
    wall = m.monotonic() - t0
    end = m.now()
    rc = child.returncode if child.returncode >= 0 else 128 - child.returncode
    write_log(settings, say, r, o, start, end, wall, rc, cgroup, before, _pressure(m, cgroup))
    if o.ran_anyway and rc != 0:
        # The last line of the command's own output, where the failure is read.
        with contextlib.suppress(OSError, ValueError):
            print(f"{SAY} these tests ran on a still-busy machine ({o.no_room}; ran with "
                  f"{value} workers): a timing failure may be the machine, not the change.",
                  file=sys.stderr, flush=True)
    return rc


def run(command: list[str], label: str, min_workers: int, max_text: str, settings: Settings,
        problems: Sequence[str], machine: Machine, say: Say) -> int:
    if not any("{workers}" in arg for arg in command):
        say(f"{SAY} the command has no {{workers}} to put the worker count in, e.g. "
            "`-- pytest -n {workers}`. Nothing was run.")
        return 2
    signals = _Signals()
    signals.install()
    started = machine.monotonic()
    r = Run(settings, problems, machine, label or Path(command[0]).name, min_workers, max_text,
            say)
    o = Outcome()
    try:
        try:
            r.admit(o)
        except _Stopped:
            raise
        except Exception as exc:  # its own fault: never hold up the commit
            o.let_go()
            o.slot = o.free = None
            if o.verbatim is None:
                o.workers = max_workers(max_text, os.cpu_count() or 1)
                if o.workers is None:
                    o.verbatim = max_text
            o.unadmitted = f"internal error: {type(exc).__name__}: {exc}"
        return _launch(command, settings, machine, say, signals, r, o)
    except _Stopped as stop:
        signals.phase = "done"  # a second signal now changes nothing
        o.let_go()
        o.slot = o.workers = None
        o.waited_s = machine.monotonic() - started
        o.unadmitted = f"stopped by {signal.Signals(stop.signum).name} while waiting"
        say(f"{SAY} {o.unadmitted} ({_dur(o.waited_s)}); nothing was run.")
        now = machine.now()
        write_log(settings, say, r, o, now, now, 0.0, 128 + stop.signum, machine.cgroup(), None,
                  None)
        return 128 + stop.signum
    finally:
        o.let_go()
        signals.restore()


# ─── status ───────────────────────────────────────────────────────────────


def status(as_json: bool, settings: Settings, problems: Sequence[str], machine: Machine,
           out: TextIO) -> int:
    s = settings
    slots, admitting = read_holders(s.slots_dir, s.cap, machine)
    cpus = machine.affinity()
    notes = list(problems)
    idle: float | None = None
    try:
        idle = measure(machine, cpus, s.window_s)
    except (OSError, ValueError) as exc:
        notes.append(f"couldn't measure the free cores: {exc}")
    report = {
        "dir": str(s.slots_dir), "cap": s.cap, "slots": slots, "admitting": admitting,
        "cores_allowed": len(cpus), "idle_cores": round(idle, 2) if idle is not None else None,
        "reserve": _num(s.reserve),
        "free_cores": round(idle - s.reserve, 2) if idle is not None else None, "notes": notes,
    }
    if as_json:
        print(json.dumps(report, indent=2), file=out)
        return 0
    if s.cap == 0:
        print("admission is off (TEST_SLOTS_MAX=0)", file=out)
    print(f"test slots in {s.slots_dir} (cap {s.cap})", file=out)
    for slot in slots:
        if not slot["held"]:
            print(f"  slot {slot['slot']}: free", file=out)
            continue
        doing = (f"running {slot['workers']} workers" if slot.get("state") == "running"
                 else "waiting for room")
        print(f"  slot {slot['slot']}: pid {slot['pid']}, {slot.get('label') or '?'}, {doing} "
              f"since {slot.get('since') or '?'}, in {slot.get('cwd') or '?'}", file=out)
    if admitting:
        print(f"being admitted: pid {admitting['pid']}, {admitting.get('label') or '?'} "
              f"({admitting.get('state') or '?'} since {admitting.get('since') or '?'})", file=out)
    else:
        print("being admitted: nobody", file=out)
    if idle is not None:
        print(f"free cores now: {idle - s.reserve:.1f} of {len(cpus)} (idle {idle:.1f}, reserve "
              f"{_num(s.reserve)})", file=out)
    for note in notes:
        print(f"note: {note}", file=out)
    return 0


# ─── The command line ─────────────────────────────────────────────────────


def _at_least_one(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is less than 1")
    return value


def _progress_writer(fd: int | None) -> tuple[Say, str | None]:
    stream: TextIO = sys.stderr
    problem = None
    if fd is not None:
        try:
            stream = open(fd, "w", buffering=1, encoding="utf-8", errors="replace", closefd=False)
        except OSError as exc:
            problem = f"--progress-fd {fd} isn't open ({exc.strerror}); progress goes to stderr"

    def say(line: str) -> None:
        with contextlib.suppress(OSError, ValueError):
            print(line, file=stream, flush=True)

    return say, problem


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None,
         machine: Machine | None = None, run_user: Path | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    machine = machine or Machine()
    parser = argparse.ArgumentParser(prog="test_slot.py",
                                     description="Start a test phase only when the machine has "
                                                 "room for it (docs/test-slots.md).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="wait for room, then run the command after --")
    run_p.add_argument("--label", default="", help="what this is, for status and the log")
    run_p.add_argument("--min-workers", type=_at_least_one, default=4)
    run_p.add_argument("--max-workers", default="8",
                       help="a whole number, or auto (the allowed cores)")
    run_p.add_argument("--progress-fd", type=int, default=None)
    status_p = sub.add_parser("status", help="the slots held and the free cores now (read-only)")
    status_p.add_argument("--json", action="store_true")
    command: list[str] = []
    if args[:1] == ["run"]:
        if "--" not in args:
            parser.error("run: put the command after --")
        cut = args.index("--")
        args, command = args[:cut], args[cut + 1:]
        if not command:
            parser.error("run: no command after --")
    opts = parser.parse_args(args)
    settings, problems = read_settings(env, run_user)
    if opts.cmd == "status":
        return status(opts.json, settings, problems, machine, sys.stdout)
    say, fd_problem = _progress_writer(opts.progress_fd)
    if fd_problem:
        say(f"{SAY} {fd_problem}")
    return run(command, opts.label, opts.min_workers, opts.max_workers, settings, problems,
               machine, say)


if __name__ == "__main__":
    sys.exit(main())
