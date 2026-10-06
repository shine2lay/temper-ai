"""Runs cut off by a crash or a restart are picked up again by themselves.

A run whose process died leaves no one to say so: its ``workflow.started``
event stays open until the next start-up, where
:func:`temper_ai.observability.reconcile.reconcile_interrupted_runs` marks it
``interrupted``. That was the end of it -- the run sat dead until a person
noticed and pressed Resume. Seventeen runs in one week ended that way, four of
them EPD builds killed by a 01:36 crash and started again by hand the next
morning.

Now temper picks them back up itself, through the same path the Resume button
uses, so a resumed run reruns only what broke (``stage/plan.py``) and its
earlier attempt stays readable on the run page.

Which ones, and why not the others
----------------------------------

:func:`choose` is the whole rule and it touches nothing: it is given what is
known about each interrupted run and returns what to pick up and, for every
other, the reason it was left. It is deliberately shy -- picking a run up
starts real work and spends real money, so anything unclear is left for a
person:

* **cancelled** -- someone stopped it. Starting it again would undo that.
* **waiting for an answer** -- parked at a gate. It is not lost: it carries on
  when the question is answered. (A Pi run that let its worker go at a gate,
  ``runner/parked.py``, is not even marked interrupted: however long it has
  waited, only the owner's answer carries it on, and start-up applies an
  answer that came in while nothing could act on it.)
* **gave up** -- someone pressed Give up, or the deadline passed, and the
  clean-ups it was holding have run. The worktree and the dev stack it needs
  are gone.
* **older than 12 hours** -- the clean-ups a stopped run holds are held for 24
  hours (``runner/holds.py``); twelve leaves room to spare. Past that the
  setup may be gone and a resume would quietly rebuild the world.
* **picked up twice already** -- a run that dies again each time it is picked
  up is a crash loop, not an accident. It is named in the message instead.
* **nothing saved to pick up from** -- no checkpoints, so there is no "where it
  stopped" to go back to.

Where the cut-off runs come from
--------------------------------

Two places, because a run dies differently depending on where it runs:

* **In temper itself** (``inprocess``): nobody can close its event, so start-up
  does it -- ``reconcile_and_report`` marks it ``interrupted`` and hands the
  list over.
* **In its own box** (``external``, which is how temper runs live): the run
  outlives a restart of the server, so start-up must *not* touch it. When the
  box died too -- the machine went down, docker restarted, the container was
  killed -- the worker's reaper notices within seconds of coming back and ends
  the run itself (``spawner/reaper.py`` -> ``settle_run_event``).

So the pick-up waits a little (:data:`SETTLE_S`) for the reaper to finish its
first sweep, and then looks for both: what start-up marked, and what was ended
as lost by this stop -- from a few minutes before the process came back
(:data:`GRACE`, because a stack on its way down can still bury a box or two)
until now. A run whose box died an hour ago while temper kept running was
already dead and seen; it is not this restart's business.

One at a time
-------------

Seventeen runs coming back at once would be its own outage, so the picks are
resumed one after another with a gap between them, and the owner gets one
message listing what came back and what did not.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from temper_ai.observability.reconcile import INTERRUPTED
from temper_ai.runner.lanes import PI_LANE
from temper_ai.shared.clock import as_utc, utcnow

logger = logging.getLogger(__name__)

# How far back a run may have been cut off and still be picked up. Inside the
# 24 hours a stopped run's clean-ups are held, with room to spare.
WINDOW = timedelta(hours=12)

# How many times temper may pick the same run up by itself. The third time it
# is left alone and named in the message, so a crash loop cannot spin.
MAX_PICKUPS = 2

# Between two resumes, so a boot does not start every lost run at once.
GAP_S = 5.0

# How long to let the dust settle before looking. Long enough for the worker to
# come up and its reaper (every 5s) to end the runs whose boxes died with it.
SETTLE_S = float(os.environ.get("TEMPER_PICK_UP_SETTLE_S", "60") or 60)

# How far back before the restart still counts as the same stop. A stack going
# down is not instant: the boxes die first and the reaper, still alive for those
# last seconds, buries some of them before the server itself goes. Without this
# they would look like runs that died during the last uptime and be left.
GRACE = timedelta(minutes=5)

SWITCH_ENV = "TEMPER_PICK_UP_INTERRUPTED"
OFF = ("0", "false", "off", "no")

# Written on the interrupted event when temper picks that attempt up. It is
# how the next start-up counts the attempts, so the count survives a restart.
STAMP = "auto_resumed"

# Why a run temper meant to pick up was left alone after all: Resume refused it (409),
# because someone else is carrying it on already. Expected, so said without alarm.
ALREADY_CARRIED_ON = "already being carried on"


def switched_on() -> bool:
    return os.environ.get(SWITCH_ENV, "1").strip().lower() not in OFF


@dataclass(frozen=True)
class Candidate:
    """What is known about one interrupted run, gathered before anything is decided."""

    execution_id: str
    workflow_name: str = ""
    event_id: str = ""
    # The run's status before it was marked interrupted: running, queued or waiting.
    status_before: str = "running"
    # The last thing this run did, by its newest event. A run started 13 hours ago
    # but cut off five minutes ago is fresh; its start time is not.
    last_active_at: datetime | None = None
    # Somebody stopped it: its row says cancelled, or a cancel is on its way.
    cancelled: bool = False
    # The clean-ups it was holding: waiting / released / done / taken_over, or None
    # when it holds none (a crash leaves no hold, and tears nothing down either).
    hold_status: str | None = None
    hold_ended_by: str | None = None
    # There is a "where it stopped" to go back to.
    has_checkpoints: bool = False
    # How many times temper has already picked this run up by itself.
    pickups: int = 0
    # Its lane (runner/lanes.py): "pi" for a Pi run, whose state is its ledger.
    lane: str | None = None


@dataclass(frozen=True)
class Choice:
    """One run and what is being done about it."""

    execution_id: str
    workflow_name: str
    pick_up: bool
    why: str
    event_id: str = ""
    pickups: int = 0

    @property
    def short(self) -> str:
        return self.execution_id[:8]


@dataclass
class Picks:
    """What a start-up decided, ready to act on and to say out loud."""

    picked: list[Choice] = field(default_factory=list)
    left: list[Choice] = field(default_factory=list)
    # Filled in as the resumes happen: runs that could not be started after all.
    failed: list[Choice] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.picked or self.left)

    def message(self, run_url: Callable[[str], str] | None = None) -> str:
        """One message for the owner: a line for each run, with the reason it was left.

        Empty when there was nothing to pick up *and* nothing to report, so an
        ordinary restart says nothing.
        """
        if not self.picked and not self.left:
            return ""

        def line(choice: Choice) -> str:
            url = (run_url(choice.execution_id) if run_url else "") or ""
            where = f" {url}" if url else ""
            return f"• {choice.workflow_name or 'a run'} {choice.short} — {choice.why}{where}"

        if self.picked:
            head = (f"temper restarted and picked {_count(len(self.picked), 'run')} "
                    "back up where they stopped.")
        else:
            head = (f"temper restarted. {_count(len(self.left), 'interrupted run')} "
                    "left alone; nothing was picked up.")
        parts = [head]
        if self.picked:
            parts.append("\nPicked up:\n" + "\n".join(line(c) for c in self.picked))
        if self.failed:
            parts.append("\nCould not be started again:\n"
                         + "\n".join(line(c) for c in self.failed))
        if self.left:
            parts.append("\nLeft alone:\n" + "\n".join(line(c) for c in self.left))
        return "\n".join(parts)


def _count(n: int, thing: str) -> str:
    return f"{n} {thing}" + ("" if n == 1 else "s")


def _ago(then: datetime | None, now: datetime) -> str:
    """"12 minutes ago", in words, for the message."""
    if then is None:
        return "at an unknown time"
    seconds = max(0.0, (now - then).total_seconds())
    if seconds < 90:
        return "moments ago"
    minutes = seconds / 60
    if minutes < 90:
        return f"{round(minutes)} minutes ago"
    return f"{round(minutes / 60)} hours ago"


def choose(
    candidates: Iterable[Candidate],
    *,
    now: datetime | None = None,
    window: timedelta = WINDOW,
    max_pickups: int = MAX_PICKUPS,
) -> Picks:
    """Which interrupted runs to pick up, and why each of the others is left.

    Pure: it reads nothing and writes nothing. Everything it needs is in the
    candidates, so the rule can be read, argued with and tested on its own.
    """
    when = now or utcnow()
    picks = Picks()
    for c in sorted(candidates, key=lambda c: (c.last_active_at or when)):
        why = _leave_because(c, when, window, max_pickups)
        if why is None:
            picks.picked.append(Choice(
                execution_id=c.execution_id, workflow_name=c.workflow_name,
                pick_up=True, event_id=c.event_id, pickups=c.pickups,
                why=f"stopped {_ago(as_utc(c.last_active_at), when)}; "
                    "picking up where it stopped",
            ))
        else:
            picks.left.append(Choice(
                execution_id=c.execution_id, workflow_name=c.workflow_name,
                pick_up=False, why=why, event_id=c.event_id, pickups=c.pickups,
            ))
    return picks


def _leave_because(
    c: Candidate, now: datetime, window: timedelta, max_pickups: int,
) -> str | None:
    """The reason to leave this run alone, or None to pick it up.

    The order is the order a person would think in: what was decided about this
    run first, then whether picking it up could still work.
    """
    if c.cancelled:
        return "it was cancelled"
    if c.status_before == "waiting":
        return "it is waiting for an answer; it carries on when that comes"
    if c.hold_ended_by == "give_up":
        return "someone gave up on it, and its clean-ups have run"
    if c.hold_status == "released":
        return "the setup it was holding was let go at its deadline"
    if c.hold_status == "done":
        return "its clean-ups have already run"
    # Taken over *by another run* means that run owns the setup now. A run takes its own
    # hold over every time it is resumed (routes.py), and that is not a reason to stop.
    if c.hold_status == "taken_over" and c.hold_ended_by not in (None, "", c.execution_id):
        return "a later attempt took it over"
    last = as_utc(c.last_active_at)
    if last is None or now - last > window:
        return (f"it stopped {_ago(last, now)}, longer ago than the "
                f"{_hours(window)} temper picks runs up from")
    if c.pickups >= max_pickups:
        return (f"temper picked it up {_count(c.pickups, 'time')} already and it "
                "stopped again; it needs a person")
    if not c.has_checkpoints and c.lane != PI_LANE:
        # A Pi run's state is its ledger (pi_ tables), not checkpoints: it resumes from that.
        return "nothing was saved to pick up from"
    if not c.workflow_name:
        return "temper cannot tell which workflow it was"
    return None


def _hours(window: timedelta) -> str:
    hours = window.total_seconds() / 3600
    whole = int(hours)
    return _count(whole, "hour") if hours == whole else f"{hours:g} hours"


# ─── what is known about each run ─────────────────────────────────────────


def cut_off_by_this_stop(
    marked: Iterable[Mapping[str, object]], *, since: datetime | None = None,
    lane: str | None = None,
) -> list[dict[str, object]]:
    """Every run this restart found dead: what start-up marked, and what was reaped.

    ``marked`` is what :func:`reconcile_and_report` returns -- runs temper was
    running itself. The others ran in their own boxes: their boxes died with the
    stack and the reaper ended them, either on its way down or on its way back,
    which is what ``since`` (a few minutes before the restart, see :data:`GRACE`)
    separates from the ones that died during the last uptime and were seen then.

    One entry per run, in the shape :func:`candidates_from` reads. Only ``lane``'s runs are
    reaped ones (runner/lanes.py): the server picks up the main lane's, the Pi lane its own.
    """
    entries = {str(m.get("execution_id") or ""): dict(m) for m in marked}
    entries.pop("", None)
    for run in _reaped_since(since or utcnow(), lane=lane):
        entries.setdefault(str(run["execution_id"]), run)
    return list(entries.values())


def _reaped_since(since: datetime, lane: str | None = None) -> list[dict[str, object]]:
    """Runs whose box was found dead after ``since``, with their open event ended.

    The reaper writes ``orphaned`` on the row and ``interrupted`` on the event;
    both are read here, so a run that ended any other way cannot slip in.
    """
    out: list[dict[str, object]] = []
    try:
        from sqlmodel import col, select

        from temper_ai.database import get_session
        from temper_ai.observability.models import Event
        from temper_ai.runner.lanes import lane_clause
        from temper_ai.runner.models import WorkflowRun

        with get_session() as session:
            rows: Any = session.exec(
                select(WorkflowRun.execution_id, WorkflowRun.workflow_name,  # type: ignore[call-overload]
                       WorkflowRun.completed_at)
                .where(WorkflowRun.status == "orphaned")
                .where(WorkflowRun.completed_at.is_not(None))  # type: ignore[union-attr]
                .where(lane_clause(col(WorkflowRun.spawner_metadata), lane))
            ).all()
            fresh = {
                str(execution_id): name
                for execution_id, name, completed in rows
                if (as_utc(completed) or since) >= since
            }
            if not fresh:
                return []
            events: Any = session.exec(
                select(Event).where(
                    Event.type == "workflow.started",
                    Event.status == INTERRUPTED,
                    Event.execution_id.in_(list(fresh)),  # type: ignore[union-attr]
                )
            ).all()
            for event in events:
                data = dict(event.data or {})
                out.append({
                    "execution_id": event.execution_id,
                    "event_id": event.id,
                    "workflow_name": str(data.get("name") or fresh.get(event.execution_id) or ""),
                    # A box run was running; the reaper does not end a queued one.
                    "status_before": "running",
                    "timestamp": as_utc(event.timestamp),
                    "lane": lane,
                })
    except Exception:
        logger.warning("Could not look for runs whose box died", exc_info=True)
    return out


def candidates_from(marked: Iterable[Mapping[str, object]]) -> list[Candidate]:
    """Gather what the rule needs about each run the marking just buried.

    ``marked`` is what :func:`reconcile_and_report` returns: one entry per run
    whose event was open and has just been set to ``interrupted``.
    """
    entries = [dict(m) for m in marked]
    ids = [str(m.get("execution_id") or "") for m in entries]
    ids = [i for i in ids if i]
    if not ids:
        return []

    held = _holds(ids)
    checkpointed = _with_checkpoints(ids)
    pickups, last_seen, cancel_seen = _history(ids)
    cancelled = _cancelled(ids) | cancel_seen

    out = []
    for m in entries:
        execution_id = str(m.get("execution_id") or "")
        if not execution_id:
            continue
        hold = held.get(execution_id) or {}
        started = as_utc(m.get("timestamp"))  # type: ignore[arg-type]
        out.append(Candidate(
            execution_id=execution_id,
            workflow_name=str(m.get("workflow_name") or ""),
            event_id=str(m.get("event_id") or ""),
            status_before=str(m.get("status_before") or "running"),
            last_active_at=last_seen.get(execution_id) or started,
            cancelled=execution_id in cancelled,
            hold_status=hold.get("status"),
            hold_ended_by=hold.get("ended_by"),
            has_checkpoints=execution_id in checkpointed,
            pickups=pickups.get(execution_id, 0),
            lane=str(m.get("lane") or "") or None,
        ))
    return out


def _cancelled(ids: Sequence[str]) -> set[str]:
    """Runs somebody stopped: their row says so, or a stop is on its way to them."""
    try:
        from sqlmodel import select

        from temper_ai.database import get_session
        from temper_ai.runner.models import WorkflowRun

        with get_session() as session:
            rows = session.exec(
                select(WorkflowRun.execution_id, WorkflowRun.status,  # type: ignore[call-overload]
                       WorkflowRun.cancel_requested)
                .where(WorkflowRun.execution_id.in_(ids)),  # type: ignore[attr-defined]
            ).all()
        return {r[0] for r in rows if r[1] == "cancelled" or r[2]}
    except Exception:
        logger.warning("Could not read which runs were stopped; leaving them alone",
                       exc_info=True)
        # Not knowing means not picking up: every candidate counts as stopped.
        return set(ids)


def _holds(ids: Sequence[str]) -> dict[str, dict[str, str | None]]:
    """The clean-up hold of each run that has one."""
    try:
        from sqlmodel import select

        from temper_ai.database import get_session
        from temper_ai.runner.models import CleanupHold

        with get_session() as session:
            rows = session.exec(
                select(CleanupHold).where(CleanupHold.execution_id.in_(ids)),  # type: ignore[attr-defined]
            ).all()
            return {r.execution_id: {"status": r.status, "ended_by": r.ended_by} for r in rows}
    except Exception:
        logger.warning("Could not read the held clean-ups", exc_info=True)
        return {}


def _with_checkpoints(ids: Sequence[str]) -> set[str]:
    """Which runs saved anything to go back to."""
    try:
        from sqlmodel import select

        from temper_ai.checkpoint.models import Checkpoint
        from temper_ai.database import get_session

        with get_session() as session:
            rows = session.exec(
                select(Checkpoint.execution_id)  # type: ignore[call-overload]
                .where(Checkpoint.execution_id.in_(ids)),  # type: ignore[attr-defined]
            ).all()
        return {r[0] if isinstance(r, tuple) else r for r in rows}
    except Exception:
        logger.warning("Could not read the checkpoints of the interrupted runs",
                       exc_info=True)
        return set()


def _history(ids: Sequence[str]) -> tuple[dict[str, int], dict[str, datetime], set[str]]:
    """How often temper has picked each run up, when each last did anything, and
    whether anyone told it to stop.

    The count is read back off the events themselves -- every attempt temper
    picked up carries a stamp -- so a restart, or ten, still sees it.

    A cancelled run normally never gets this far: its event is already
    ``cancelled``, which the marking leaves alone. But a cancel that arrived in
    the seconds before the crash may not have landed on the run's own event yet,
    and a gate someone rejected says the same thing in another way. Either is
    taken as "a person said no".
    """
    pickups: dict[str, int] = {}
    last: dict[str, datetime] = {}
    cancelled: set[str] = set()
    try:
        from sqlmodel import select

        from temper_ai.database import get_session
        from temper_ai.observability.models import Event
        from temper_ai.observability.script_logs import SCRIPT_LOG

        # Not a script's saved log rows: output, not steps (and up to ~10 MB a script, each
        # carried here whole by Event.data).
        with get_session() as session:
            rows = session.exec(
                select(Event.execution_id, Event.type, Event.data,  # type: ignore[call-overload]
                       Event.timestamp, Event.status)
                .where(Event.execution_id.in_(ids), Event.type != SCRIPT_LOG),  # type: ignore[union-attr]
            ).all()
        for execution_id, etype, data, timestamp, status in rows:
            when = as_utc(timestamp)
            if when is not None and (execution_id not in last or when > last[execution_id]):
                last[execution_id] = when
            if etype == "workflow.started" and isinstance(data, dict) and data.get(STAMP):
                pickups[execution_id] = pickups.get(execution_id, 0) + 1
            if status in ("cancelled", "rejected"):
                cancelled.add(execution_id)
            elif isinstance(data, dict) and (
                data.get("cancelled_reason") or data.get("gate_status") == "rejected"
            ):
                cancelled.add(execution_id)
    except Exception:
        logger.warning("Could not read the story of the interrupted runs", exc_info=True)
    return pickups, last, cancelled


# ─── picking them up ──────────────────────────────────────────────────────


def pick_up_interrupted(
    marked: Iterable[Mapping[str, object]],
    *,
    now: datetime | None = None,
    gap_s: float = GAP_S,
    settle_s: float | None = None,
    since: datetime | None = None,
    resume: Callable[[str], None] | None = None,
    tell: Callable[[str], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    lane: str | None = None,
) -> Picks:
    """Pick up what should be picked up, one at a time, and say what happened.

    Waits ``settle_s`` first: the runs that died in their own boxes are ended by
    the worker's reaper a few seconds after it comes back, and picking up before
    that would miss every one of them.

    ``lane`` is whose reaped runs these are (runner/lanes.py): the server's start-up picks up
    the main lane's, the Pi lane's start-up (runner/pi_lane.py) its own.

    Never raises: a start-up must finish even when none of this works.
    """
    picks = Picks()
    try:
        if not switched_on():
            logger.info("Picking interrupted runs up again is off (%s)", SWITCH_ENV)
            return picks
        started = (since or utcnow()) - GRACE
        settle = SETTLE_S if settle_s is None else settle_s
        if settle > 0:
            sleep(settle)
        picks = choose(candidates_from(cut_off_by_this_stop(marked, since=started, lane=lane)),
                       now=now)
        if not picks:
            return picks

        from temper_ai.runner.resume_authority import (
            ResumeAttemptRefused,
            automatic_resume_refused,
            read_resume_authority,
            record_saved_stop,
            refuse_resume,
        )
        from temper_ai.runner.resume_claim import only_while_cut_off

        start = resume or _resume_through_the_button
        for i, choice in enumerate(list(picks.picked)):
            if i:
                sleep(gap_s)
            try:
                if automatic_resume_refused(choice.execution_id):
                    raise ResumeAttemptRefused("resume_requires_explicit_request",
                                               execution_id=choice.execution_id)
                authority = read_resume_authority(choice.execution_id)
                if authority.stopped:
                    record_saved_stop(choice.execution_id, authority)
                    picks.picked.remove(choice)
                    picks.left.append(Choice(
                        execution_id=choice.execution_id, workflow_name=choice.workflow_name,
                        pick_up=False, event_id=choice.event_id, pickups=choice.pickups,
                        why="it was cancelled",
                    ))
                    continue
                _stamp_attempt(choice.event_id, choice.pickups + 1)
                # What this stop cut off, and nothing newer: a run somebody carried on since
                # it was chosen is theirs, and its Resume says so (409, left alone below).
                with only_while_cut_off():
                    start(choice.execution_id)
                logger.warning("Picked %s (%s) back up where it stopped",
                               choice.short, choice.workflow_name)
            except ResumeAttemptRefused as refused:
                refuse_resume(choice.execution_id, refused)
                picks.picked.remove(choice)
                picks.left.append(Choice(
                    execution_id=choice.execution_id, workflow_name=choice.workflow_name,
                    pick_up=False, event_id=choice.event_id, pickups=choice.pickups,
                    why=f"resume attempt refused: {refused.code}; explicit Resume is needed",
                ))
            except Exception as exc:  # noqa: BLE001 - one bad run must not stop the rest
                picks.picked.remove(choice)
                if getattr(exc, "status_code", None) == 409:
                    # Someone else is carrying it on already (Resume, an answer, another
                    # start-up): expected, and nothing went wrong. Left alone, said below.
                    picks.left.append(Choice(
                        execution_id=choice.execution_id, workflow_name=choice.workflow_name,
                        pick_up=False, event_id=choice.event_id, pickups=choice.pickups,
                        why=ALREADY_CARRIED_ON,
                    ))
                    continue
                logger.error("Could not pick %s back up: %s", choice.short, exc, exc_info=True)
                picks.failed.append(Choice(
                    execution_id=choice.execution_id, workflow_name=choice.workflow_name,
                    pick_up=False, event_id=choice.event_id, pickups=choice.pickups,
                    why=f"temper could not start it again: {exc}",
                ))

        for choice in picks.left:
            logger.info("Left %s (%s) alone: %s", choice.short, choice.workflow_name, choice.why)

        text = picks.message(run_url=_run_url)
        if text:
            (tell or _tell_owner)(text)
    except Exception:  # noqa: BLE001 - never stop the server from starting
        logger.error("Picking interrupted runs back up failed (carrying on)", exc_info=True)
    return picks


def _resume_through_the_button(execution_id: str) -> None:
    """Resume exactly the way the Resume button does, so nothing behaves differently."""
    from temper_ai.api.caller import acting_as
    from temper_ai.api.routes import ResumeRequest, resume_run

    # The server itself picks the run up at start-up: done under the name "pickup".
    with acting_as("pickup", via="pickup"):
        resume_run(execution_id, ResumeRequest())


def _stamp_attempt(event_id: str, attempt: int) -> None:
    """Write on the attempt that temper picked it up, so the next start-up can count."""
    if not event_id:
        return
    from temper_ai.database import get_session
    from temper_ai.observability.models import Event

    with get_session() as session:
        event = session.get(Event, event_id)
        if event is None:
            return
        data = dict(event.data or {})
        data[STAMP] = {"at": utcnow().isoformat(), "attempt": attempt}
        event.data = data
        session.add(event)


def _run_url(execution_id: str) -> str:
    try:
        from temper_ai.integrations.slack.config import load_config

        return load_config().run_url(execution_id)
    except Exception:
        return ""


def _tell_owner(text: str) -> bool:
    from temper_ai.integrations.slack.owner import tell_owner

    return tell_owner(text)


def pick_up_in_the_background(
    marked: Iterable[Mapping[str, object]], *, since: datetime | None = None,
) -> threading.Thread | None:
    """Start the pick-up on a thread of its own: start-up does not wait for it.

    Started even when start-up marked nothing: on a live temper the lost runs are
    the ones whose boxes died, and those are ended a little later by the reaper.
    ``since`` is the moment this process came back -- runs ended before it were
    already dead during the last uptime, and are not this restart's business.
    """
    entries = [dict(m) for m in marked]
    if not switched_on():
        return None
    thread = threading.Thread(
        target=pick_up_interrupted, args=(entries,), kwargs={"since": since or utcnow()},
        name="pick-up-interrupted", daemon=True,
    )
    thread.start()
    return thread
