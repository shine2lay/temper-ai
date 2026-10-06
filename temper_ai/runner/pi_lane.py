"""The Pi lane's own steps (M4 ADR-M4-01, -05, -06, -11; HOME-REVIEW H2, H4; docs/pi-lane.md).

The Pi lane is the pi-worker service: a watcher (``temper watch-queue`` with
``TEMPER_LANE=pi``) that claims only Pi runs, one at a time, and starts each as a child
process beside the Docker socket its member boxes need. Around those runs it does what this
module holds:

* **at its start** (:func:`start_up`): sweep leftover member boxes by exact name and label,
  end the previous instance's runs (their processes went with its container), and pick up
  the Pi runs that a stop cut off, from their ledger;
* **in each run process, before the run** (:func:`check_run`): the run's lane must be this
  process's lane, both ways; then, in the Pi lane, every temper module is imported up front
  (H2: a deploy that changes the code on disk never mixes into a run), the Pi-only rule is
  checked again on the workflow as it loads now, the preflight runs (runner/pi_preflight.py)
  and the temper commit the attempt runs on is recorded with the pins the preflight checked
  and the host's Pi version (SW-16);
* **when it stops** (:func:`drain`): it claims nothing more, raises a drain mark its runs see at
  their next turn boundary (:func:`leave_if_draining`), and waits for them to leave;
* **for temper-deploy** (:func:`lane_status`): which Pi runs are active, parked or queued, read
  from database rows only, without a model, a credential or the Pi switch.

Every decision here reads database rows (H4): claim, cancel, waits and their answers, the
account state. A Redis message at most wakes something up; it decides nothing.
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from temper_ai.runner.lanes import (
    LANE_RECORD_KEY,
    OUTSIDE_PI_LANE,
    PI_LANE,
    LaneSettingError,
    in_pi_lane,
    lane_clause,
    lane_for,
    lane_of,
    pi_only_problems,
    this_lane,
)
from temper_ai.shared.clock import utcnow

logger = logging.getLogger(__name__)

#: Where the drain mark is: set by the Pi lane's watcher at its start, read by its runs.
DRAIN_MARK_ENV = "TEMPER_PI_DRAIN_MARK"
#: How long a stopping Pi lane waits for its runs to reach a turn boundary: under the
#: pi-worker's stop_grace_period (960 s), which is a turn's hang guard (900 s) plus room.
DRAIN_DEADLINE_S = 930.0
#: A run process that left at a turn boundary because the Pi lane is stopping.
DRAINED_EXIT = 75
#: A run process that refused its run (the lane, the Pi-only rule, the preflight).
REFUSED_EXIT = 3
#: The commits a Pi run's row keeps (one per attempt).
COMMITS_KEPT = 20
#: What a refused non-Pi run in the Pi lane says.
NOT_A_PI_RUN = "the Pi lane runs only Pi runs"
#: A commit the code's checkout doesn't say.
UNKNOWN_COMMIT = "unknown"
#: The checkout this code runs from. In pi-worker that is /app, with temper's ``.git`` mounted
#: read-only at /app/.git (SW-16, SW-38): pi-worker only, never a member box or a run box.
CODE_ROOT = Path(__file__).resolve().parents[2]
#: Why the active runs are active (lane-status).
TURN_RUNNING = "turn_running"
CLAIMED = "claimed"

_SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
_CREDENTIALS = re.compile(r"://[^@/\s]+@")


# --- Drain (ADR-M4-06, SW-48) ----------------------------------------------------------------

class LaneDrained(BaseException):  # noqa: N818 - not an error: the lane is stopping
    """The Pi lane is stopping: this run leaves at a turn boundary, with no turn half done.

    A BaseException, so no step's ``except Exception`` turns it into a failure: it goes up to
    ``temper run-workflow``, which ends the attempt as interrupted, and the next start of the
    Pi lane picks the run up from its ledger."""


def drain_mark() -> Path | None:
    raw = os.environ.get(DRAIN_MARK_ENV, "").strip()
    return Path(raw) if raw else None


def arm_drain_mark() -> Path:
    """At the watcher's start: where its runs look for the mark (they inherit the setting),
    and no mark left from before."""
    path = drain_mark() or Path(tempfile.gettempdir()) / "temper-pi-lane" / "draining"
    os.environ[DRAIN_MARK_ENV] = str(path)
    path.unlink(missing_ok=True)
    return path


def set_draining() -> None:
    path = drain_mark()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(utcnow().isoformat())


def draining() -> bool:
    """Whether this run's Pi lane is stopping (only ever true inside the Pi lane)."""
    path = drain_mark()
    return path is not None and in_pi_lane() and path.exists()


def leave_if_draining(where: str) -> None:
    """At a turn boundary: leave now if the Pi lane is stopping."""
    if draining():
        logger.warning("The Pi lane is stopping: leaving at a turn boundary (%s)", where)
        raise LaneDrained(where)


def drain(spawner: Any, *, deadline_s: float = DRAIN_DEADLINE_S, poll_s: float = 1.0,
          sleep: Callable[[float], None] = time.sleep,
          clock: Callable[[], float] = time.monotonic) -> list[str]:
    """The watcher, stopping: raise the mark, then wait for its runs to leave (each at its
    next turn boundary, or parked). Returns the runs still going at the deadline; those end
    with the container, and the next start picks them up."""
    set_draining()
    live = getattr(spawner, "live_runs", None)
    left = list(live()) if callable(live) else []
    if left:
        logger.warning("The Pi lane is stopping: waiting up to %.0f s for %s to reach a turn "
                       "boundary", deadline_s, ", ".join(left))
    end = clock() + deadline_s
    while left and clock() < end:
        sleep(poll_s)
        left = list(live()) if callable(live) else []
    if left:
        logger.error("The Pi lane stopped with %s still going; the next start picks them up",
                     ", ".join(left))
    return left


# --- The watcher (ADR-M4-01, H1) -------------------------------------------------------------

def worker_problem(spawner: Any) -> str | None:
    """Why this process can't be the Pi lane's watcher; None when it can."""
    kind = getattr(getattr(spawner, "kind", None), "value", None)
    if kind != "subprocess":
        return ("the Pi lane starts its runs as child processes (TEMPER_SPAWNER=subprocess), "
                f"not with the {kind} spawner")
    from temper_ai import pi_agent

    if not pi_agent.enabled():
        return f"the Pi lane needs {pi_agent.SWITCH_ENV}=1"
    return None


# --- Each run, before it starts --------------------------------------------------------------

@dataclass(frozen=True)
class Refusal:
    """Why a run process didn't start its run: ``kind`` is ``lane``, ``pi_preflight``,
    ``project_folder`` (the team's folder, checked on its real paths) or ``account`` (the
    run's one account could not be settled). Its message leaves with every login token
    withheld: it is logged, stored on the run's row and in its refused attempt (SW-52)."""

    kind: str
    message: str

    def __post_init__(self) -> None:
        from temper_ai.pi_agent.token_scan import withhold

        object.__setattr__(self, "message", withhold(str(self.message)))


def check_run(execution_id: str, run_row: dict, *, start: str | None,
              graph_loader: Any) -> Refusal | None:
    """The run process's gate, before the run is marked running (run_workflow.py).

    Outside the Pi lane an unmarked run passes untouched and a Pi run is refused (SW-42).
    In the Pi lane a run that isn't a Pi run is refused; a Pi run gets every temper module
    imported now (H2), the Pi-only rule on the workflow as it loads now (SW-41, at claim),
    the preflight (ADR-M4-05), the team's project folder on its real paths and the run's one
    account (:func:`claim_checks`), and its commit recorded with the pins the preflight
    checked and the host's Pi version (SW-16)."""
    try:
        here = this_lane()
    except LaneSettingError as exc:
        return Refusal("lane", str(exc))
    lane = lane_of(run_row.get("spawner_metadata"))
    if here != PI_LANE:
        if lane == PI_LANE:
            return Refusal("lane", f"{OUTSIDE_PI_LANE}: a worker that isn't the Pi lane "
                                   f"claimed this Pi run, so it didn't start")
        return None
    if lane != PI_LANE:
        return Refusal("lane", f"{NOT_A_PI_RUN}: this run isn't marked for the Pi lane, so "
                               f"the Pi lane didn't start it")
    eager_import()
    # Every log line of a Pi run leaves with its login tokens withheld (SW-52).
    from temper_ai.pi_agent.token_scan import guard_logs

    guard_logs()
    nodes, problems = _pi_only_now(run_row, graph_loader)
    if problems:
        return Refusal("lane", "The Pi lane runs only Pi steps, team stages of Pi members "
                               "and gates: " + "; ".join(problems))
    from temper_ai.runner.pi_preflight import preflight

    seen: dict[str, Any] = {}
    failed = preflight(record=seen)
    if failed:
        return Refusal("pi_preflight", "The Pi lane's checks before the run failed: "
                       + "; ".join(f"{reason}: {text}" for reason, text in failed))
    commit, why = read_commit()
    if commit is None:
        # The preflight read it a moment ago: refuse rather than record "unknown" (SW-16).
        return Refusal("pi_preflight", "The Pi lane's checks before the run failed: "
                                       f"commit_unreadable: {why}")
    refusal = claim_checks(execution_id, run_row, nodes)
    if refusal is not None:
        return refusal
    record_commit(execution_id, start, commit, pins=seen.get("pins"),
                  host_pi=seen.get("host_pi"))
    return None


def _pi_only_now(run_row: dict, graph_loader: Any) -> tuple[list[Any], list[str]]:
    """The workflow as it loads now (loaded once) and its Pi-only problems."""
    name = str(run_row.get("workflow_name") or "")
    try:
        nodes, config = graph_loader.load_workflow(name, inputs=run_row.get("inputs") or {})
    except Exception as exc:  # noqa: BLE001 - the run itself reports a workflow that won't load
        logger.warning("Pi lane: workflow %s didn't load for the Pi-only check (%s); the run "
                       "reports it", name, type(exc).__name__)
        return [], []
    if lane_for(nodes) != PI_LANE:
        return nodes, [f"workflow '{name}' has no Pi step any more"]
    return nodes, pi_only_problems(nodes, getattr(config, "safety", None))


# --- At claim, before any copy or model call (ADR-M4-12, ADR-M4-09) --------------------------

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def has_team(nodes: Any) -> bool:
    """Whether the workflow has a team stage (the only Pi step that copies a project)."""
    from temper_ai.runner.lanes import _walk

    return any(type(node).__name__ == "TeamNode" for _path, node in _walk(nodes or ()))


def recorded_start_commits(execution_id: str) -> list[str]:
    """The commits a run's team copies started from, as recorded under the Pi state root
    (none before the first copy, or when the box config can't be read)."""
    from temper_ai.pi_agent.team_check import load_box
    from temper_ai.pi_agent.team_leader import ProjectCopies

    if not _RUN_ID.fullmatch(execution_id or ""):
        return []
    box, _problem = load_box()
    if box is None:
        return []
    commits: list[str] = []
    for record in sorted((Path(box.state_root) / execution_id).glob("*/project.json")):
        commit = ProjectCopies.recorded(record.parent).get("commit")
        if isinstance(commit, str) and commit and commit not in commits:
            commits.append(commit)
    return commits


def folder_problems_at_claim(execution_id: str, path: str) -> list[str]:
    """The team's project folder, checked on its real paths by the same function the team's
    node runs before it makes a copy (team_folders.folder_check, authoritative): inside a
    listed root, the top of a git work tree whose git folders are inside the roots, with its
    start commit (the one its copies started from, once recorded), no link leading out."""
    from temper_ai.pi_agent.team_config import load_team_config
    from temper_ai.pi_agent.team_folders import folder_check, roots_of

    roots = roots_of(load_team_config().project_roots)
    commits = recorded_start_commits(execution_id)
    if not commits:
        return folder_check(path, roots, authoritative=True, fresh=True)[0]
    problems: list[str] = []
    for commit in commits:
        for problem in folder_check(path, roots, authoritative=True, fresh=False,
                                    start_commit=commit)[0]:
            if problem not in problems:
                problems.append(problem)
    return problems


def admitted_before(run_row: dict) -> bool:
    """Whether the run passed a claim before: an attempt's commit is on its row (SW-16),
    written only once the claim's checks passed."""
    meta = run_row.get("spawner_metadata") or {}
    record = meta.get(LANE_RECORD_KEY) if isinstance(meta, dict) else None
    return bool(isinstance(record, dict) and record.get("commits"))


def claim_checks(execution_id: str, run_row: dict, nodes: Any) -> Refusal | None:
    """What the Pi lane settles when it claims a run, before any copy or model call: a team's
    project folder on its real paths (ADR-M4-12, SW-33), then the run's one account -- kept
    from an earlier attempt, else picked at the run's first claim by the account-room file
    from the allowed slots and recorded on the run, where a second claim finds it and keeps
    it (ADR-M4-09, -14, -18). A refusal names why; nothing is copied and no model is called."""
    workspace = run_row.get("workspace_path")
    if workspace and has_team(nodes):
        problems = folder_problems_at_claim(execution_id, str(workspace))
        if problems:
            return Refusal("project_folder", "The Pi lane's checks of the team's project "
                                             "folder failed: " + "; ".join(problems))
    from temper_ai.pi_agent.accounts import AccountError, settle

    try:
        # The account the database keeps stands, checked like any recorded account.
        settle(execution_id, run_row, admitted=admitted_before(run_row))
    except AccountError as exc:
        return Refusal("account", f"The Pi lane couldn't settle the run's account: {exc}")
    return None


def record_refusal(execution_id: str, run_row: dict, refusal: Refusal, *,
                   resume_of: str | None = None) -> None:
    """Make a refused attempt show on the run page: a failed ``workflow.started`` event that
    names why (without it, a refused resume would show the attempt before it)."""
    from temper_ai.observability.event_recorder import EventRecorder
    from temper_ai.observability.event_types import EventType

    data: dict[str, Any] = {
        "name": run_row.get("workflow_name"),
        "node_count": 0,
        "input_data": run_row.get("inputs") or {},
        "workspace_path": run_row.get("workspace_path"),
        "error": refusal.message,
        "refused": refusal.kind,
    }
    if resume_of:
        data["resume_of"] = resume_of
    try:
        EventRecorder(execution_id).record(EventType.WORKFLOW_STARTED, data=data,
                                           execution_id=execution_id, status="failed")
    except Exception:  # noqa: BLE001 - the row still says why
        logger.warning("Could not record %s's refused attempt", execution_id, exc_info=True)


# --- H2: everything imported before the first turn -------------------------------------------

def eager_import() -> tuple[int, list[str]]:
    """Import every temper module now, at the run process's start (every resume is a new run
    process): code that changes on disk during the run (a deploy updates the checkout the
    Pi lane mounts) never mixes into it (H2, SW-76). Returns (imported, failed)."""
    import temper_ai

    imported, failed = 0, []
    for info in pkgutil.walk_packages(temper_ai.__path__, "temper_ai.",
                                      onerror=lambda name: failed.append(name)):
        if info.name.rsplit(".", 1)[-1] == "__main__":
            continue
        try:
            importlib.import_module(info.name)
            imported += 1
        except Exception as exc:  # noqa: BLE001 - an optional extra's module
            failed.append(f"{info.name} ({type(exc).__name__})")
    if failed:
        logger.info("Pi lane: %d temper module(s) didn't import (optional parts): %s",
                    len(failed), ", ".join(failed[:10]))
    return imported, failed


# --- SW-16: the commit each attempt runs on --------------------------------------------------

def temper_commit(root: Path | None = None) -> str:
    """The temper commit this code is from (:func:`read_commit`); ``unknown`` when it can't be
    read. Outside the Pi lane (in-process, dev, CI) that is all; in the Pi lane an unreadable
    commit is a preflight refusal, ``commit_unreadable`` (runner/pi_preflight.py)."""
    sha, _why = read_commit(root)
    return sha or UNKNOWN_COMMIT


def read_commit(root: Path | None = None) -> tuple[str | None, str]:
    """``(sha, "")`` for the temper commit this code is from, or ``(None, why)``.

    Read from the checkout's ``.git`` files (HEAD, the branch it names, or packed-refs) as
    ``git rev-parse HEAD`` answers, without running git: nothing on that mount runs, no hook,
    no fsmonitor, and no ownership check to trip."""
    base = root or CODE_ROOT
    dot_git = base / ".git"
    try:
        if dot_git.is_file():  # a worktree: "gitdir: <path>"
            text = dot_git.read_text().strip()
            if not text.startswith("gitdir:"):
                return None, f"{dot_git} is neither a git folder nor a worktree's pointer"
            gitdir = (base / text.split(":", 1)[1].strip()).resolve()
        elif dot_git.is_dir():
            gitdir = dot_git
        else:
            return None, f"there is no {dot_git}"
        common = gitdir
        if (gitdir / "commondir").is_file():
            common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
        head = (gitdir / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            if _SHA.fullmatch(head):
                return head, ""
            return None, f"{gitdir / 'HEAD'} names no commit"
        ref = head.split(":", 1)[1].strip()
        if not ref.startswith("refs/"):
            return None, f"{gitdir / 'HEAD'} names {ref!r}, not a branch"
        for folder in (gitdir, common):
            loose = folder / ref
            if loose.is_file():
                sha = loose.read_text().strip()
                if _SHA.fullmatch(sha):
                    return sha, ""
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text().splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref and _SHA.fullmatch(parts[0]):
                    return parts[0], ""
        return None, f"HEAD names {ref}, which {common} doesn't hold"
    except OSError as exc:
        return None, (f"{exc.filename or dot_git} can't be read "
                      f"({exc.strerror or type(exc).__name__})")


def record_commit(execution_id: str, start: str | None, commit: str | None = None, *,
                  pins: dict[str, Any] | None = None, host_pi: str | None = None) -> str:
    """Write the commit this attempt runs on (``commit``, else read now) into the run's row
    (``spawner_metadata`` ``pi_lane.commits``: one entry per attempt, start and every resume)
    and the log; with it, given them, the pins the preflight checked (``pins``: each pin's
    digest by name, :mod:`temper_ai.pi_agent.pins`) and the host's Pi version (SW-16)."""
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    commit = commit or temper_commit()
    entry: dict[str, Any] = {"at": utcnow().isoformat(), "start": start or "new",
                             "commit": commit}
    if pins is not None:
        entry["pins"] = pins
    if host_pi is not None:
        entry["host_pi"] = host_pi
    try:
        with get_session() as session:
            row = session.exec(
                select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).first()
            if row is not None:
                meta = dict(row.spawner_metadata or {})
                record = dict(meta.get(LANE_RECORD_KEY) or {})
                kept = list(record.get("commits") or [])[-(COMMITS_KEPT - 1):]
                record["commits"] = [*kept, entry]
                meta[LANE_RECORD_KEY] = record
                row.spawner_metadata = meta
                session.add(row)
    except Exception:  # noqa: BLE001 - the log line below still has it
        logger.warning("Could not record %s's commit on its row", execution_id, exc_info=True)
    logger.info("Pi run %s (%s) runs on temper %s", execution_id, entry["start"], commit)
    return commit


# --- At the Pi lane's start (ADR-M4-06, SW-49) -----------------------------------------------

class _GoneSpawner:
    """The previous pi-worker's runs: their processes went with its container. A fresh
    process-id check could match an unrelated process of the new container."""

    from temper_ai.worker_proto import SpawnerKind as _Kind

    kind = _Kind.subprocess

    def is_alive(self, handle: Any) -> bool:
        return False

    def is_gone(self, handle: Any) -> bool:
        return True

    def kill(self, handle: Any, *, force: bool = False) -> None:
        return None


class CarriedOnAlready(RuntimeError):
    """Someone else is carrying the run on already (pickup reads ``status_code``)."""

    status_code = 409


def start_up(*, docker: Callable[..., Any] | None = None,
             now: Any = None) -> dict[str, Any]:
    """Before the Pi lane claims anything: sweep leftover member boxes, put back the runs
    the previous instance had claimed but not started, end the ones it was running (an
    uncertain turn becomes a recovery wait when the run resumes: Ledger.take_over), and
    pick up the Pi runs that a stop cut off. Never raises."""
    out: dict[str, Any] = {"boxes": [], "requeued": 0, "picked_up": [], "left": []}
    try:
        out["boxes"] = sweep_member_boxes(docker=docker)
    except Exception:  # noqa: BLE001
        logger.error("Pi lane: sweeping leftover member boxes failed", exc_info=True)
    try:
        out["requeued"] = _requeue_unstarted()
        from temper_ai.spawner.reaper import Reaper

        Reaper(_GoneSpawner(), lane=PI_LANE).tick()  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        logger.error("Pi lane: ending the previous instance's runs failed", exc_info=True)
    from temper_ai.runner.pickup import WINDOW, pick_up_interrupted

    when = now or utcnow()
    picks = pick_up_interrupted([], now=when, since=when - WINDOW, settle_s=0,
                                resume=resume_in_the_lane, tell=_log_only, lane=PI_LANE)
    out["picked_up"] = [c.execution_id for c in picks.picked]
    out["left"] = [c.execution_id for c in picks.left]
    return out


def _log_only(text: str) -> bool:
    logger.warning("Pi lane start-up: %s", text)
    return True


def sweep_member_boxes(*, docker: Callable[..., Any] | None = None) -> list[dict]:
    """Stop and remove every member box left from before: the names of unsettled turns in the
    ledger, and every container labelled as one, each by its exact name (never a prune)."""
    from temper_ai.pi_agent import box as pibox

    run = docker or pibox._docker_cli
    names = set(_ledger_box_names())
    got = run("ps", "-a", "--filter", "label=temper.pi.box=1", "--format", "{{.Names}}",
              timeout=30)
    if getattr(got, "returncode", 1) == 0:
        names |= {n.strip() for n in str(got.stdout or "").splitlines() if n.strip()}
    else:
        logger.warning("Pi lane: couldn't list member boxes (docker ps failed)")
    return [pibox.stop_leftover_box(name, docker=docker)
            for name in sorted(names) if pibox.BOX_NAME.match(name)]


def _ledger_box_names() -> list[str]:
    import sqlalchemy as sa

    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import UNSETTLED, turns

    engine = get_database().engine
    if not sa.inspect(engine).has_table(turns.name):
        return []
    with engine.connect() as conn:
        rows = conn.execute(sa.select(turns.c.box_name).where(
            turns.c.state.in_(UNSETTLED), turns.c.box_name.is_not(None))).all()
    return [str(r[0]) for r in rows if r[0]]


def _requeue_unstarted() -> int:
    """Pi runs the previous instance claimed but never got running: back in the queue."""
    from sqlalchemy import update
    from sqlmodel import col

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        stmt = (update(WorkflowRun)
                .where(col(WorkflowRun.status) == "queued",
                       col(WorkflowRun.spawner_kind).is_not(None),
                       lane_clause(col(WorkflowRun.spawner_metadata), PI_LANE))
                .values(spawner_kind=None, spawner_handle=None))
        return int(session.exec(stmt).rowcount or 0)  # type: ignore[call-overload]


def resume_in_the_lane(execution_id: str) -> None:
    """Carry a cut-off Pi run on from its ledger, as Resume does for one (SW-80's claim first,
    so no other resume starts a second copy), without the server."""
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner import holds, resume_claim
    from temper_ai.runner.models import WorkflowRun
    from temper_ai.runner.queue import queue_run

    token = resume_claim.claim(execution_id, by="the Pi lane's start-up")
    if token is None:
        raise CarriedOnAlready(f"{execution_id} is already being carried on")
    try:
        with get_session() as session:
            row = session.exec(
                select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).first()
            if row is None:
                raise LookupError(f"no row for {execution_id}")
            name, workspace, inputs = row.workflow_name, row.workspace_path, row.inputs
        holds.take_over(execution_id, by=execution_id)
        queue_run(execution_id, name, workspace, inputs or {}, start="resume",
                  extra={"rerun": []})
    except BaseException:
        resume_claim.release(execution_id, token)
        raise


# --- lane-status: for temper-deploy (Systems rm-a8af8c68) ------------------------------------

class LaneStatusError(RuntimeError):
    """lane-status can't answer (a plain message, never credentials)."""


def status_engine(url: str | None = None) -> Any:
    """An engine of its own for lane-status: the configured database only, never a default
    (an empty stand-in database would answer "nothing active"), and never a table made."""
    import sqlalchemy as sa
    from sqlalchemy.pool import NullPool

    url = url or os.environ.get("TEMPER_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise LaneStatusError("no database is configured (TEMPER_DATABASE_URL)")
    if url.startswith("sqlite"):
        return sa.create_engine(url, poolclass=NullPool)
    return sa.create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})


def lane_status(engine: Any) -> dict[str, Any]:
    """The Pi lane's runs, read from database rows only (H4): ``active`` (a member turn is
    running, or the run is claimed and not parked), ``parked`` (waiting with no process) and
    ``queued`` (not claimed yet). Only ids, why and wait kinds: no content. Reads, never
    creates (missing pi_ tables mean no turns). Raises on any failure: the caller says so."""
    import sqlalchemy as sa

    from temper_ai.pi_agent.ledger import turns, waits
    from temper_ai.runner.models import WorkflowRun

    wr = WorkflowRun.__table__  # type: ignore[attr-defined]
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(wr.c.execution_id, wr.c.status, wr.c.spawner_kind)
            .where(lane_clause(wr.c.spawner_metadata, PI_LANE))
            .where(wr.c.status.in_(("queued", "running", "waiting")))
            .order_by(wr.c.created_at)).all()
        ids = [str(r[0]) for r in rows]
        inspector = sa.inspect(conn)
        turning: set[str] = set()
        open_waits: dict[str, list[str]] = {}
        if ids and inspector.has_table(turns.name):
            turning = {str(r[0]) for r in conn.execute(
                sa.select(turns.c.run_id).where(turns.c.run_id.in_(ids),
                                                turns.c.state == "running"))}
        if ids and inspector.has_table(waits.name):
            for run_id, kind in conn.execute(
                    sa.select(waits.c.run_id, waits.c.kind)
                    .where(waits.c.run_id.in_(ids), waits.c.state == "open")
                    .order_by(waits.c.opened_at)):
                open_waits.setdefault(str(run_id), []).append(str(kind))
    active: list[dict[str, str]] = []
    parked: list[dict[str, str]] = []
    queued: list[dict[str, str]] = []
    for execution_id, status, kind in rows:
        run_id = str(execution_id)
        if run_id in turning:
            active.append({"run_id": run_id, "why": TURN_RUNNING})
        elif status == "waiting":
            parked.append({"run_id": run_id,
                           "waiting_on": (open_waits.get(run_id) or ["gate"])[0]})
        elif status == "running" or kind is not None:
            active.append({"run_id": run_id, "why": CLAIMED})
        else:
            queued.append({"run_id": run_id})
    return {"ok": True, "checked_at": utcnow().isoformat(), "active": active,
            "parked": parked, "queued": queued}


def plain_error(exc: BaseException) -> str:
    """An error for lane-status's answer: its kind and first line, no credentials."""
    first = (str(exc).strip().splitlines() or [""])[0]
    return f"{type(exc).__name__}: {_CREDENTIALS.sub('://***@', first)[:200]}".rstrip(": ")
