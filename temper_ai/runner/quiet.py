"""Is this run still getting anywhere? One rule, used everywhere.

A run that dies quietly says nothing. Its ``workflow.started`` event stays
open, the listing keeps saying "running", and the only way to find out is for
somebody to open the page and notice that nothing has moved. An EPD build sat
that way for ten hours on 2026-09-29 before anyone looked.

Five states, and only one of them is bad:

``finished``
    It ended -- completed, failed, cancelled or interrupted. Nothing to say.
``waiting``
    It is parked at a gate, waiting for a person. Healthy, not stuck: it
    carries on the moment the question is answered. The page says "waiting on
    you", never "quiet", however long it has been -- the wait is the point.
``parked``
    Every account's model allowance is spent, so the run is waiting for the
    allowance to reopen at a known moment (:mod:`temper_ai.llm.allowance`).
    Like a gate it is a healthy wait and never quiet, but unlike a gate it
    wants nothing from anybody: the page says "waiting for allowance, back
    around 14:20" and the notify loop leaves it alone.
``quiet``
    Still marked running, nobody is being asked anything, and no event has
    been written for longer than the run's threshold. This is the one worth
    saying out loud.
``healthy``
    Anything else: it wrote something recently enough, or it is too young to
    judge, or temper does not know when it last did anything (in which case it
    says nothing rather than cry wolf).

The threshold is :data:`DEFAULT_AFTER` unless the workflow sets its own, which
is what ``quiet_after`` in a workflow file is for::

    name: epd_loop
    quiet_after: 2h        # a deploy step of this one really does take hours

Ten minutes of silence is alarming in a one-minute notify run and ordinary in
a build, so the number belongs with the workflow, not in one global setting.

Who uses it
-----------

* the API (``api/data_service.py``) so the run list and the run page can show
  "quiet for 2h 14m" with the last thing the run did;
* the notify loop (``integrations/notify/loop.py``), which sends the one
  message about it, through the same path as every other notice about a run,
  once per quiet spell -- it already remembers what it has sent, so a second
  check says nothing a second time.

This module only says what is true. Nothing here cancels, restarts or nudges a
run: picking a stuck run back up is a separate decision made somewhere else.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temper_ai.shared.clock import as_utc, utcnow

logger = logging.getLogger(__name__)

# No event for this long and a running run is quiet, unless its workflow says
# otherwise. Half an hour: long enough for a slow model call or a long tool,
# short enough that a dead run is found the same morning.
DEFAULT_AFTER = timedelta(minutes=30)

# Statuses that mean the run is over. "interrupted" is a run a restart found
# open; it is over too, whatever happens to it next.
FINISHED = ("completed", "failed", "cancelled", "interrupted")

HEALTHY = "healthy"
WAITING = "waiting"
PARKED = "parked"
QUIET = "quiet"
DONE = "finished"

# The event a parked run leaves open while it waits (EventType.LLM_ALLOWANCE).
# Named here rather than imported so this module keeps reading nothing.
ALLOWANCE_EVENT = "llm.allowance"

# How long a workflow's own threshold is remembered before it is read again.
CONFIG_CACHE_S = 60.0


@dataclass(frozen=True)
class Run:
    """What is known about one run, before anything is decided about it.

    Facts only, so the rule below can be read and tested without a database.
    """

    execution_id: str
    workflow_name: str = ""
    # As the listing reports it: running / waiting / completed / failed / ...
    status: str = "running"
    # The newest event of this run. None when it has written none at all.
    last_activity_at: datetime | None = None
    started_at: datetime | None = None
    # A gate of this run is waiting for an answer.
    at_a_gate: bool = False
    # The last thing it did, in words ("deploy · waiting for an OK").
    last_step: str = ""
    # This workflow's own threshold, when it sets one.
    after: timedelta | None = None
    # When the model allowance this run is waiting on reopens. Set only while
    # the run is parked for it; None the rest of the time.
    parked_until: datetime | None = None


@dataclass(frozen=True)
class Verdict:
    """What the rule makes of one run."""

    execution_id: str
    state: str                      # healthy | waiting | quiet | finished
    # Since when it has been in this state: the last event for quiet and
    # healthy runs, None when nothing is known.
    since: datetime | None = None
    # How long nothing has happened. None for a finished run.
    idle: timedelta | None = None
    # The threshold that was applied, for the page to explain itself with.
    after: timedelta = DEFAULT_AFTER
    last_step: str = ""
    # When a parked run expects to carry on. Only ever set with state parked.
    parked_until: datetime | None = None

    @property
    def quiet(self) -> bool:
        return self.state == QUIET

    @property
    def waiting(self) -> bool:
        """Healthily waiting -- on a person or on the allowance. Never quiet."""
        return self.state in (WAITING, PARKED)

    @property
    def how_long(self) -> str:
        """"2h 14m" -- how long it has been quiet, or waiting."""
        return how_long(self.idle)

    def sentence(self, workflow: str = "") -> str:
        """One line a person can read, for a message or a tooltip."""
        who = f"{workflow} " if workflow else ""
        short = self.execution_id[:8]
        if self.state == QUIET:
            last = f" Last: {self.last_step}." if self.last_step else ""
            return (f"{who}{short} has been quiet for {self.how_long} "
                    f"(nothing new for longer than {how_long(self.after)}).{last}")
        if self.state == WAITING:
            return f"{who}{short} is waiting on you, {self.how_long} so far."
        if self.state == PARKED:
            back = f" back around {self.parked_until:%H:%M} UTC" if self.parked_until else ""
            return f"{who}{short} is waiting for the model allowance,{back or ' no end time given'}."
        if self.state == DONE:
            return f"{who}{short} has ended."
        return f"{who}{short} is getting on with it."


def how_long(span: timedelta | None) -> str:
    """A span in words: "under a minute", "45m", "2h 14m", "3d 4h".

    Every one of these is read after "for": "quiet for ...", "needs you,
    ... so far". "just now" names a moment, not a length, so it came out as
    "quiet for just now" -- and a gate reads that way for its first minute,
    every time.
    """
    if span is None:
        return "an unknown time"
    seconds = int(max(0.0, span.total_seconds()))
    if seconds < 60:
        return "under a minute"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


def look(run: Run, *, now: datetime | None = None,
         default_after: timedelta = DEFAULT_AFTER) -> Verdict:
    """What state this run is in. Pure: it reads nothing and writes nothing.

    The order is the order a person would think in: is it over, is it waiting
    for me, do I know when it last did anything, and only then the clock.
    """
    when = now or utcnow()
    after = run.after or default_after
    last = as_utc(run.last_activity_at) or as_utc(run.started_at)
    idle = (when - last) if last is not None else None

    def verdict(state: str, *, since: datetime | None = last,
                span: timedelta | None = idle,
                until: datetime | None = None) -> Verdict:
        return Verdict(execution_id=run.execution_id, state=state, since=since,
                       idle=span, after=after, last_step=run.last_step,
                       parked_until=until)

    if run.status in FINISHED:
        return verdict(DONE, since=None, span=None)
    # Waiting out a spent allowance is as healthy as a gate, and is checked
    # first: a run can only be parked while it is running, and staying silent
    # for hours is exactly what it is meant to do. Checked before the clock so
    # task #23 never calls it quiet.
    if run.parked_until is not None:
        return verdict(PARKED, until=as_utc(run.parked_until))
    # A gate is a run doing exactly what it should: waiting for a person. The
    # listing already turns that into the status "waiting"; both are accepted
    # so a caller that has one and not the other still gets it right.
    if run.at_a_gate or run.status == WAITING:
        return verdict(WAITING)
    # Queued, pending, or anything else not yet running: it has not started
    # writing events, so silence says nothing about it.
    if run.status != "running":
        return verdict(HEALTHY)
    if last is None or idle is None:
        return verdict(HEALTHY)
    return verdict(QUIET if idle >= after else HEALTHY)


def looks(runs: Iterable[Run], *, now: datetime | None = None,
          default_after: timedelta = DEFAULT_AFTER) -> dict[str, Verdict]:
    """The same rule over many runs, by execution id."""
    when = now or utcnow()
    return {r.execution_id: look(r, now=when, default_after=default_after) for r in runs}


# ─── the last thing a run did ─────────────────────────────────────────────

# What each kind of event means, in words. The name of the step, agent or tool
# is put in front of it where there is one.
_VERBS = {
    "workflow.started": "started",
    "stage.started": "started",
    "stage.completed": "finished",
    "stage.failed": "failed",
    "agent.started": "working",
    "agent.completed": "finished",
    "agent.failed": "failed",
    "llm.call.started": "thinking",
    "llm.call.completed": "thought",
    "llm.call.failed": "a model call failed",
    "llm.iteration": "thinking",
    "llm.retry": "retrying a model call",
    "llm.fallback": "fell back to another model",
    "llm.allowance": "waiting for the model allowance",
    "tool.call.started": "running a tool",
    "tool.call.completed": "ran a tool",
    "tool.call.failed": "a tool failed",
    "tool.blocked": "a tool was blocked",
    "tool.timeout": "a tool timed out",
    "dispatch.applied": "added steps",
    "safety.policy.triggered": "a safety rule fired",
}


def last_step_label(event_type: str, data: Mapping[str, Any] | None = None,
                    status: str = "") -> str:
    """The last thing a run did, in a few words: "deploy · waiting for an OK".

    Built from one event, so it costs nothing beyond the row the caller
    already has. An event temper does not have words for is named as it is.
    """
    d = dict(data or {})
    name = str(d.get("node_name") or d.get("agent_name") or d.get("name") or "").strip()
    tool = str(d.get("tool_name") or d.get("tool") or "").strip()
    if event_type == "stage.started" and (d.get("gate") or d.get("gate_status")):
        gate_status = str(d.get("gate_status") or status or "waiting")
        said = "waiting for an OK" if gate_status == "waiting" else f"gate {gate_status}"
        return f"{name} · {said}" if name else said
    verb = _VERBS.get(event_type, event_type)
    if tool and event_type.startswith("tool."):
        verb = f"{verb.replace('a tool', tool)}"
    return f"{name} · {verb}" if name else verb


# ─── the facts, from the database ─────────────────────────────────────────


def after_for(workflow_name: str, fallback: timedelta | None = None) -> timedelta:
    """This workflow's own ``quiet_after``, or ``fallback``, or the default.

    Read from the stored workflow config, which is where a run's own settings
    live; a workflow with nothing to say about it, or one temper cannot read,
    simply gets the fallback.
    """
    raw = _workflow_quiet_after(workflow_name)
    return raw or fallback or DEFAULT_AFTER


_cache: dict[str, tuple[float, timedelta | None]] = {}


def _workflow_quiet_after(workflow_name: str) -> timedelta | None:
    from time import monotonic

    if not workflow_name:
        return None
    hit = _cache.get(workflow_name)
    now = monotonic()
    if hit is not None and now - hit[0] < CONFIG_CACHE_S:
        return hit[1]
    value = _read_quiet_after(workflow_name)
    _cache[workflow_name] = (now, value)
    return value


def forget_thresholds() -> None:
    """Drop the remembered thresholds (tests, and a config that just changed)."""
    _cache.clear()


def _read_quiet_after(workflow_name: str) -> timedelta | None:
    from temper_ai.config.store import ConfigStore

    try:
        config = ConfigStore().get(workflow_name, "workflow")
    except Exception:  # noqa: BLE001 - no config, no threshold; never a failed page
        return None
    # The store hands back the file as written, outer ``workflow:`` and all,
    # so the setting sits one level down. Accept it either way: the same
    # config arrives unwrapped from other callers, and a threshold that
    # silently reads as "nothing here" is exactly the bug this went live
    # with -- every workflow quietly back on the 45-minute default.
    body = config.get("workflow", config)
    if not isinstance(body, dict):
        body = config
    return parse_after(body.get("quiet_after"), where=workflow_name)


def parse_after(value: Any, *, where: str = "") -> timedelta | None:
    """``quiet_after`` as written -- "45m", "2h", 900 -- or None when unusable."""
    if value is None or value is False or value == "":
        return None
    from temper_ai.triggers.cron import CronError, parse_duration

    try:
        return timedelta(seconds=parse_duration(value))
    except CronError as exc:
        logger.warning("quiet_after in %s is not a duration (%s); using the default",
                       where or "the workflow", exc)
        return None


@dataclass(frozen=True)
class Activity:
    """The newest event of a run: when it was, and what it was."""

    at: datetime
    step: str = ""
    # Set when that newest event is a park still open: when it wakes. A parked
    # run writes nothing while it waits, so its park *is* the newest event --
    # which is why this costs no extra query.
    parked_until: datetime | None = None


def activity_of(execution_ids: Iterable[str]) -> dict[str, Activity]:
    """The last thing each of these runs did. Two queries, however many runs.

    Asked for the runs on a page, so it stays small; an id with no events at
    all is simply missing from the answer.
    """
    ids = [e for e in dict.fromkeys(execution_ids) if e]
    if not ids:
        return {}
    from sqlalchemy import and_, func, or_
    from sqlmodel import col, select

    from temper_ai.database import get_session
    from temper_ai.observability.models import Event

    with get_session() as session:
        newest = session.exec(
            select(Event.execution_id, func.max(Event.timestamp))
            .where(col(Event.execution_id).in_(ids))
            .group_by(col(Event.execution_id)),
        ).all()
        pairs = [(eid, at) for eid, at in newest if eid and at is not None]
        if not pairs:
            return {}
        # The rows themselves, for what the run was doing. One OR per run
        # rather than a window function: the same SQL on Postgres and SQLite.
        rows = session.exec(
            select(Event.execution_id, Event.type, Event.status, Event.data)
            .where(or_(*[and_(col(Event.execution_id) == eid, col(Event.timestamp) == at)
                         for eid, at in pairs])),
        ).all()

    steps: dict[str, str] = {}
    parked: dict[str, datetime] = {}
    for eid, kind, status, data in rows:
        steps.setdefault(str(eid), last_step_label(str(kind or ""), data, str(status or "")))
        if str(kind or "") == ALLOWANCE_EVENT and str(status or "") == "waiting":
            until = moment((data or {}).get("until"))
            if until is not None:
                parked.setdefault(str(eid), until)
    return {
        str(eid): Activity(at=as_utc(at) or at, step=steps.get(str(eid), ""),
                           parked_until=parked.get(str(eid)))
        for eid, at in pairs
    }


def verdicts_for(runs: Iterable[Mapping[str, Any]], *, gated: set[str] | None = None,
                 now: datetime | None = None,
                 default_after: timedelta | None = None) -> dict[str, Verdict]:
    """Look at each run of a listing: the facts are gathered here.

    ``runs`` are listing rows (``id``, ``workflow_name``, ``status``,
    ``start_time``). Finished runs are answered without touching the database
    -- there is nothing to ask about a run that is over.
    """
    when = now or utcnow()
    rows = [dict(r) for r in runs if r.get("id")]
    live = [r for r in rows if str(r.get("status") or "") not in FINISHED]
    activity = activity_of([str(r["id"]) for r in live]) if live else {}
    fallback = default_after or _notify_stuck_after() or DEFAULT_AFTER
    out: dict[str, Verdict] = {}
    for row in rows:
        eid = str(row["id"])
        workflow = str(row.get("workflow_name") or "")
        seen = activity.get(eid)
        out[eid] = look(
            Run(
                execution_id=eid,
                workflow_name=workflow,
                status=str(row.get("status") or "running"),
                last_activity_at=seen.at if seen else None,
                started_at=moment(row.get("start_time")),
                at_a_gate=bool(gated and eid in gated),
                last_step=seen.step if seen else "",
                after=after_for(workflow, fallback) if eid in activity else None,
                parked_until=seen.parked_until if seen else None,
            ),
            now=when,
            default_after=fallback,
        )
    return out


def moment(value: Any) -> datetime | None:
    """A time from a listing row: a datetime, an ISO string, or nothing."""
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, str) and value:
        try:
            return as_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _notify_stuck_after() -> timedelta | None:
    """What the notify settings call quiet, so the page and the message agree."""
    try:
        from temper_ai.integrations.notify.config import load_config

        return load_config().stuck_after
    except Exception:  # noqa: BLE001 - no notify settings: the default stands
        return None
