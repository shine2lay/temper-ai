"""Where temper-ci keeps its things, and the few names everything shares."""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import subprocess
from pathlib import Path

HOME = Path.home()
MAIN_REPO = Path(os.environ.get("TEMPER_CI_MAIN", HOME / "temper-ai"))
GH_REPO = os.environ.get("TEMPER_CI_REPO", "shine2lay/temper-ai")
BASE_BRANCH = os.environ.get("TEMPER_CI_BRANCH", "master")

# Only these people's pushes get a status here. A branch of the repository
# itself can only be pushed by someone with write access, and a fork's pull
# request is never a branch here — but the list is the second lock, so a new
# collaborator's push is never passed on to master by accident.
ALLOWED_PUSHERS = tuple(
    p.strip() for p in os.environ.get("TEMPER_CI_PUSHERS", "shine2lay").split(",") if p.strip()
)

STATE = Path(os.environ.get("TEMPER_CI_STATE", HOME / ".local/state/temper-ci"))
REPORTS = STATE / "reports"          # one folder per commit
MIRROR = STATE / "mirror"            # a clone of its own, so ~/temper-ai is never touched
GATE_STATE = STATE / "gate.json"     # what each commit's check came to
DEPLOY_STATE = STATE / "deploy.json"  # the last deploy and the last good commit
LOCK = STATE / "gate.lock"           # one check at a time
LOG = STATE / "gate.log"

# The commit status GitHub requires. The name is older than the rule that there
# is one temper only: nothing is built or run for it any more (gate.py).
CONTEXT = "temper/boxes"
REPORT_PORT = int(os.environ.get("TEMPER_CI_REPORT_PORT", "8434"))
REPORT_BASE = os.environ.get("TEMPER_CI_REPORT_BASE", f"http://127.0.0.1:{REPORT_PORT}")


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def stamp() -> str:
    return now().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    for d in (STATE, REPORTS, MIRROR.parent):
        d.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def log(message: str) -> None:
    line = f"{stamp()} {message}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def sh(*cmd: str, cwd: Path | None = None, timeout: int = 120,
       env: dict[str, str] | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        list(cmd), cwd=str(cwd) if cwd else None, capture_output=True, text=True,
        timeout=timeout, env=env, check=False, input=stdin,
    )


def free_port() -> int:
    """A port nothing is listening on right now."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
