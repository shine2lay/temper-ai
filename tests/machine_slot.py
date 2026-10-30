"""Put parallel local pytest runs in wt's existing machine pool, not a second pool."""

import os
import shutil
import sys

MARKER = "TEMPER_PYTEST_MACHINE_SLOT"
_SKIP = ("PYTEST_XDIST_WORKER", "PYTEST_CURRENT_TEST", "CI", "GITHUB_ACTIONS", MARKER)


def enter_machine_slot(workers: int | str | None) -> None:
    """Restart this interpreter under ``wt slot`` before pytest starts workers."""
    if workers not in ("auto", "logical") and (workers is None or int(workers) <= 0):
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
