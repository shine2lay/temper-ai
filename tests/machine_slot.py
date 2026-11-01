"""Start local test runs where this machine wants them: one shared test CPU, one pool of slots.

Two jobs, one decision per run (docs/shared-test-cpu-host.md):

- Placement (Ops' test-cpu launcher; agent-tools docs/test-cpu-contract.md): once the host's
  policy is enabled, every test run belongs inside the shared test-CPU slice. A run outside it
  starts again inside it; a run already inside it (a land's checks, an outer entry, a nested run)
  carries on. Only the kernel's answer counts: no marker, variable or missing tool switches it
  off, and a run that can't be placed stops with 125 before its tests start.
- Admission (wt's machine pool): a parallel run (-n) takes one of wt's machine slots through
  ``wt slot``, the pool ``wt land`` takes for its checks. wt finds a slot an ancestor holds, so a
  nested run never waits for its own.

With no policy installed (today) or an inactive one, both work exactly as before.

As a script, for the pre-commit hook before it does anything else and for commands started by hand:
``machine_slot.py placement`` prints inactive, inside or outside; ``machine_slot.py enter --
<command...>`` becomes the command where the host wants it (through the launcher when outside,
directly otherwise). Both exit 125 when the placement can't be known or made.
"""

import json
import os
import shutil
import stat
import subprocess
import sys

MARKER = "TEMPER_PYTEST_MACHINE_SLOT"
_SKIP = ("PYTEST_XDIST_WORKER", "PYTEST_CURRENT_TEST", "CI", "GITHUB_ACTIONS", MARKER)

# The installed launcher and the host's policy (test-cpu-contract.md). Fixed on purpose: a variable
# that moved them would be a hidden way to switch placement off.
TEST_CPU = "/usr/local/libexec/test-cpu/bin/test-cpu"
POLICY = "/etc/agent-tools/test-cpu.json"
# "pid:start" of the process that restarted this run to place it. Only a guard against a loop: it
# counts only while that process is this run itself (a launcher that ran it in place) or one of its
# ancestors.
RESTART = "TEMPER_TEST_CPU_RESTART"
QUERY_SECONDS = 60
EXIT_PLACEMENT = 125


class HostEntryError(Exception):
    """The run can't start where the host's enabled (or unreadable) policy wants it."""


def _one_line(value: object) -> str:
    return " ".join(str(value).split())


def _absent(path: str) -> bool:
    """True when ``path`` is missing below real, searchable folders; False when something is there.

    A file, symlink or unsearchable folder on the way raises: "doesn't exist" for the whole path
    can't tell those apart from a clean absence.
    """
    current = "/"
    for part in path.strip("/").split("/"):
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise HostEntryError(f"can't read {current} ({_one_line(exc)})") from None
        if not stat.S_ISDIR(info.st_mode):
            raise HostEntryError(f"{current} is not a folder, so {path} can't be ruled out")
        if not os.access(current, os.X_OK):
            raise HostEntryError(f"{current} can't be searched, so {path} can't be ruled out")
        current = os.path.join(current, part)
        try:
            os.lstat(current)
        except FileNotFoundError:
            return True
        except OSError as exc:
            raise HostEntryError(f"can't read {current} ({_one_line(exc)})") from None
    return False


def host_placement() -> str:
    """'inactive', 'inside' or 'outside' the shared test CPU, as the installed launcher sees it."""
    if _absent(TEST_CPU):
        if _absent(POLICY):
            return "inactive"
        raise HostEntryError(f"{POLICY} is there but its launcher {TEST_CPU} is not; finish or undo the setup")
    if not os.path.isfile(TEST_CPU) or not os.access(TEST_CPU, os.X_OK):
        raise HostEntryError(f"{TEST_CPU} is not an executable file")
    asked = f"{TEST_CPU} membership --json"
    try:
        done = subprocess.run([TEST_CPU, "membership", "--json"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=QUERY_SECONDS)
    # ValueError: an answer that isn't text (UnicodeDecodeError) can't be read either.
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise HostEntryError(f"{asked}: {_one_line(exc)}") from None
    said = f"{asked} said {_one_line(done.stdout)[:200]!r} {_one_line(done.stderr)[:200]!r}, exit {done.returncode}"
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        raise HostEntryError(said) from None
    if done.returncode not in (0, 1) or not isinstance(answer, dict) or "error" in answer:
        raise HostEntryError(said)
    mode = answer.get("mode")
    if mode in ("absent", "inactive"):
        return "inactive"
    if mode == "enabled" and answer.get("inside") is True and done.returncode == 0:
        return "inside"
    if mode == "enabled" and answer.get("inside") is False and done.returncode == 1:
        return "outside"
    raise HostEntryError(said)


def _process(pid: int) -> tuple[str, int]:
    """("pid:start", parent pid) of a live process, from /proc."""
    with open(f"/proc/{pid}/stat", "rb") as f:
        data = f.read()
    fields = data[data.rindex(b")") + 2:].split()
    return f"{pid}:{int(fields[19])}", int(fields[1])


def _ancestors():
    """The "pid:start" of each process above this one, its parent first."""
    pid = _process(os.getpid())[1]
    while pid > 0:
        record, parent = _process(pid)
        yield record
        pid = parent


def entry_placement() -> str:
    """host_placement(), except that our own restart coming back outside fails instead of looping."""
    where = host_placement()
    record = os.environ.get(RESTART)
    if where != "outside" or record is None:
        return where
    try:
        restarted = record == _process(os.getpid())[0] or record in _ancestors()
    except (OSError, ValueError, IndexError) as exc:
        raise HostEntryError(f"{RESTART}={record} is set and this run's parents can't be read ({_one_line(exc)})") from None
    if restarted:
        raise HostEntryError(f"restarted by {record} to enter the shared test CPU, yet still outside it")
    return where


def _restart(argv: list[str], *, marker: bool, record: bool) -> None:
    """Become ``argv``; on failure put the environment back and raise HostEntryError."""
    saved = {name: os.environ.get(name) for name in (MARKER, RESTART)}
    try:
        if record:
            os.environ[RESTART] = _process(os.getpid())[0]
        if marker:
            os.environ[MARKER] = "1"
        os.execvp(argv[0], argv)
    except (OSError, ValueError, IndexError) as exc:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        raise HostEntryError(f"couldn't restart under {argv[0]} ({_one_line(exc)})") from None


def _enter_pool_as_before(parallel: bool) -> None:
    """No policy, or an inactive one: wt's pool for parallel runs, exactly as before."""
    if not parallel:
        return
    if any(name in os.environ for name in _SKIP) or shutil.which("wt") is None:
        return

    # Only prevents this restart from repeating. wt owns nested-slot detection,
    # admission, worker defaults, bounded waiting and release; don't duplicate them.
    os.environ[MARKER] = "1"
    try:
        os.execvp("wt", ["wt", "slot", "--", sys.executable, *sys.orig_argv[1:]])
    except OSError as exc:
        os.environ.pop(MARKER, None)
        reason = " ".join(str(exc).splitlines())
        print(f"temper pytest: couldn't restart under wt slot ({reason}); running unwrapped", file=sys.stderr)


def enter_machine_slot(workers: int | str | None) -> None:
    """Restart this pytest, before it starts workers, where the host wants it (module docstring).

    Raises HostEntryError when the host's policy is enabled (or unreadable) and the run can't get
    there; the caller stops the run with EXIT_PLACEMENT.
    """
    parallel = workers in ("auto", "logical") or (workers is not None and int(workers) > 0)
    where = entry_placement()
    if where == "inactive":
        _enter_pool_as_before(parallel)
        return
    marked = any(name in os.environ for name in _SKIP)
    # A run that is marked (CI, a nested test, a worker, an earlier restart) or serial takes no slot,
    # as before; on an enabled host that only skips admission, never placement.
    admit = parallel and not marked
    if admit and shutil.which("wt") is None:
        raise HostEntryError("wt is not on PATH; with the test-CPU policy enabled a parallel run takes a "
                             "machine slot through wt slot: put wt on PATH or run without -n")
    command = [sys.executable, *sys.orig_argv[1:]]
    # wt slot runs its command through the same launcher, so outside it also places the run.
    if admit:
        _restart(["wt", "slot", "--", *command], marker=True, record=where == "outside")
    elif where == "outside":
        _restart([TEST_CPU, "exec", "--quiet", "--", *command], marker=False, record=True)


def _run_here(command: list[str]) -> int:
    """Become ``command`` where this process already is; a shell's 127 or 126 if it can't start."""
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        print(f"shared test CPU: couldn't run {command[0]} ({_one_line(exc)})", file=sys.stderr)
        return 127 if isinstance(exc, FileNotFoundError) else 126


def main(argv: list[str]) -> int:
    try:
        if argv == ["placement"]:
            print(entry_placement())
            return 0
        if len(argv) > 2 and argv[:2] == ["enter", "--"]:
            # Asked first, so one command works with no policy, inside the slice and outside it.
            if entry_placement() != "outside":
                return _run_here(argv[2:])
            _restart([TEST_CPU, "exec", "--quiet", "--", *argv[2:]], marker=False, record=True)
    except HostEntryError as exc:
        print(f"shared test CPU: {exc}", file=sys.stderr)
        return EXIT_PLACEMENT
    print("usage: machine_slot.py placement | machine_slot.py enter -- <command...>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
