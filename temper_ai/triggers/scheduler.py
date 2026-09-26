"""Triggers that temper fires by itself: on a schedule, when a run finishes,
and when a run looks stuck.

Rules live beside the Linear ones in ``configs/triggers/`` and are re-read
on every tick, so a new or edited rule takes effect within a tick without a
restart::

    trigger:                          # every weekday at 9 AM Pacific
      name: morning_digest
      source: schedule
      on:
        cron: "0 9 * * 1-5"           # or   every: 30m
        timezone: America/Los_Angeles
        catch_up: false               # see "missed" below
      workflow: digest
      inputs:
        day: "{{ due[:10] }}"

    trigger:                          # start b022 once b019's run is done
      name: b022_after_b019
      source: run
      on:
        workflow: epd_loop
        status: completed             # or a list, or "any" (every end state)
        inputs: {bet: b019}           # optional: only runs started with these
      workflow: epd_loop
      inputs:
        bet: b022
        after: "{{ run.id }}"

    trigger:                          # alert when a run goes quiet
      name: stuck_alert
      source: stuck
      on:
        after: 45m                    # no new event for this long
        workflow: epd_plan            # optional
      workflow: notify_stuck
      inputs:
        run_id: "{{ run.id }}"

What each kind does at the edges (the owner's choices, 2026-09-25):

* A schedule that fell due while temper was down is skipped and recorded
  as missed; ``catch_up: true`` runs it once, late, instead. Only the
  latest missed time is considered: a week of downtime is one decision.
* A schedule whose previous run is still going skips this time.
* A new rule never fires for runs that finished before it was first seen.
* A stuck alert fires once per run. Runs parked at a gate are waiting for
  a person, not stuck, and are left alone unless ``waiting: true``.

Every decision, started or skipped, is one row in ``trigger_fires``, unique
per (rule, occasion): see ``GET /api/triggers``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from temper_ai.triggers.cron import Cron, CronError, parse_duration, zone
from temper_ai.triggers.rules import (
    Trigger,
    TriggerConfigError,
    load_triggers,
    render_inputs,
)

logger = logging.getLogger(__name__)

SCHEDULE = "schedule"
RUN = "run"
STUCK = "stuck"
SOURCES = (SCHEDULE, RUN, STUCK)

TICK_S = 30.0
# A due time noticed later than this counts as missed rather than late:
# long enough for a slow tick, short enough that "temper was down" is clear.
GRACE = timedelta(minutes=5)
END_STATES = ("completed", "failed", "cancelled", "interrupted")
# How far back a "run" rule looks for finished runs on each tick.
RECENT_RUNS = 300


# -- rule checking ---------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """A rule's ``on:`` block, checked once per load."""

    trigger: Trigger
    cron: Cron | None = None
    every: timedelta | None = None
    tz: Any = None
    catch_up: bool = False
    workflows: frozenset[str] = frozenset()
    statuses: frozenset[str] = frozenset()
    inputs: tuple[tuple[str, str], ...] = ()
    after: timedelta | None = None
    waiting: bool = False


def _names(value: Any, what: str) -> frozenset[str]:
    items = value if isinstance(value, (list, tuple)) else [value]
    names = frozenset(str(v).strip() for v in items if v is not None and str(v).strip())
    if not names:
        raise TriggerConfigError(f"'{what}' is required")
    return names


def plan(trigger: Trigger) -> Plan:
    """Check a rule's ``on:`` for its source; raises TriggerConfigError."""
    on = trigger.on
    try:
        if trigger.source == SCHEDULE:
            if ("cron" in on) == ("every" in on):
                raise TriggerConfigError("a schedule needs exactly one of 'cron' or 'every'")
            return Plan(
                trigger,
                cron=Cron.parse(on["cron"]) if "cron" in on else None,
                every=timedelta(seconds=parse_duration(on["every"])) if "every" in on else None,
                tz=zone(on.get("timezone")),
                catch_up=bool(on.get("catch_up", False)),
            )
        if trigger.source == RUN:
            status = on.get("status", "completed")
            statuses = frozenset(END_STATES) if status == "any" else _names(status, "status")
            unknown = statuses - set(END_STATES)
            if unknown:
                raise TriggerConfigError(f"status {sorted(unknown)} is not one of {list(END_STATES)} or 'any'")
            wanted = on.get("inputs") or {}
            if not isinstance(wanted, dict):
                raise TriggerConfigError("'inputs' under 'on' must be a mapping")
            return Plan(
                trigger,
                workflows=_names(on.get("workflow"), "workflow"),
                statuses=statuses,
                inputs=tuple(sorted((str(k), str(v)) for k, v in wanted.items())),
            )
        if trigger.source == STUCK:
            if "after" not in on:
                raise TriggerConfigError("'after' is required (e.g. 45m)")
            workflows = _names(on["workflow"], "workflow") if on.get("workflow") else frozenset()
            return Plan(
                trigger,
                after=timedelta(seconds=parse_duration(on["after"])),
                workflows=workflows,
                waiting=bool(on.get("waiting", False)),
            )
    except CronError as exc:
        raise TriggerConfigError(str(exc)) from exc
    raise TriggerConfigError(f"source '{trigger.source}' is not one of {list(SOURCES)}")


def load_plans(config_dir: str | Path | None = None) -> list[Plan]:
    plans = []
    for trigger in load_triggers(config_dir):
        if trigger.source not in SOURCES or not trigger.enabled:
            continue
        try:
            plans.append(plan(trigger))
        except TriggerConfigError as exc:
            logger.warning("Skipped trigger %s (%s): %s", trigger.name, trigger.path, exc)
    return plans


# -- schedule arithmetic ---------------------------------------------------


def last_due(p: Plan, since: datetime, now: datetime, anchor: datetime) -> tuple[datetime | None, int]:
    """The latest due time in (since, now], and how many fell in that window.

    ``anchor`` is when an ``every`` rule was first seen: it falls due at
    anchor + k * interval.
    """
    if p.every is not None:
        step = p.every.total_seconds()
        k_now = int((now - anchor).total_seconds() // step)
        k_since = int((since - anchor).total_seconds() // step)
        if k_now <= k_since or k_now < 1:
            return None, 0
        return anchor + timedelta(seconds=k_now * step), k_now - max(k_since, 0)
    assert p.cron is not None
    local_since = since.astimezone(p.tz).replace(second=0, microsecond=0)
    t = now.astimezone(p.tz).replace(second=0, microsecond=0)
    latest, count = None, 0
    # Walk back minute by minute over the gap only: a 30 s tick looks at one
    # or two minutes; a day of downtime at 1,440.
    while t > local_since:
        if p.cron.matches(t):
            count += 1
            if latest is None:
                latest = t
        t -= timedelta(minutes=1)
    return (latest.astimezone(UTC) if latest else None), count


def next_due(p: Plan, now: datetime, anchor: datetime) -> datetime | None:
    if p.every is not None:
        step = p.every.total_seconds()
        k = int((now - anchor).total_seconds() // step) + 1
        return anchor + timedelta(seconds=k * step)
    assert p.cron is not None
    found = p.cron.next_after(now.astimezone(p.tz))
    return found.astimezone(UTC) if found else None


# -- storage -----------------------------------------------------------------


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def state_for(name: str, now: datetime) -> tuple[datetime, datetime | None]:
    """(first_seen, checked_at) for a rule, creating its row on first sight."""
    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerState

    with get_session() as session:
        row = session.get(TriggerState, name)
        if row is None:
            row = TriggerState(trigger=name, first_seen=now, checked_at=None)
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                row = session.get(TriggerState, name)
                assert row is not None
        return _aware(row.first_seen) or now, _aware(row.checked_at)


def mark_checked(name: str, when: datetime) -> None:
    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerState

    with get_session() as session:
        row = session.get(TriggerState, name)
        if row is not None:
            row.checked_at = when
            session.add(row)
            session.commit()


def claim(name: str, key: str, outcome: str = "starting", detail: str = "") -> int | None:
    """Record a decision about one occasion; None if it was already decided."""
    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerFire

    with get_session() as session:
        row = TriggerFire(trigger=name, key=key, outcome=outcome, detail=detail[:500])
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return None
        return row.id


def settle(fire_id: int, outcome: str, detail: str = "", execution_id: str | None = None) -> None:
    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerFire

    with get_session() as session:
        row = session.get(TriggerFire, fire_id)
        if row is not None:
            row.outcome, row.detail, row.execution_id = outcome, detail[:500], execution_id
            session.add(row)
            session.commit()


def decided(name: str, keys: list[str]) -> set[str]:
    if not keys:
        return set()
    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerFire

    with get_session() as session:
        rows = session.exec(
            select(TriggerFire.key).where(TriggerFire.trigger == name, col(TriggerFire.key).in_(keys))
        ).all()
        return set(rows)


def last_started(name: str) -> str | None:
    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerFire

    with get_session() as session:
        row = session.exec(
            select(TriggerFire)
            .where(TriggerFire.trigger == name, TriggerFire.outcome == "started")
            .order_by(col(TriggerFire.at).desc())
            .limit(1)
        ).first()
        return row.execution_id if row else None


def history(name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerFire

    with get_session() as session:
        stmt = select(TriggerFire)
        if name:
            stmt = stmt.where(TriggerFire.trigger == name)
        rows = session.exec(stmt.order_by(col(TriggerFire.at).desc()).limit(limit)).all()
        return [
            {"trigger": r.trigger, "key": r.key, "at": r.at.replace(tzinfo=r.at.tzinfo or UTC).isoformat(),
             "outcome": r.outcome, "detail": r.detail, "execution_id": r.execution_id}
            for r in rows
        ]


# -- what runs exist ---------------------------------------------------------


def _runs(status: str | None = None) -> list[dict[str, Any]]:
    from temper_ai.api.data_service import list_workflow_executions

    return list_workflow_executions(limit=RECENT_RUNS, status=status)["runs"]


def _run_inputs(execution_id: str) -> dict[str, Any]:
    from temper_ai.observability.event_types import EventType
    from temper_ai.observability.recorder import get_events

    events = get_events(execution_id=execution_id, event_type=EventType("workflow.started"), limit=1)
    data = (events[0].get("data") if events else None) or {}
    inputs = data.get("input_data") or {}
    return inputs if isinstance(inputs, dict) else {}


def _last_activity(execution_id: str) -> datetime | None:
    from temper_ai.database import get_session
    from temper_ai.observability.models import Event

    with get_session() as session:
        value = session.exec(
            select(func.max(Event.timestamp)).where(Event.execution_id == execution_id)
        ).first()
        return _aware(value) if isinstance(value, datetime) else None


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return _aware(datetime.fromisoformat(text))
    except ValueError:
        return None


def _still_going(execution_id: str | None) -> str | None:
    from temper_ai.api.hooks import _run_still_going

    return _run_still_going(execution_id)


# -- the tick ----------------------------------------------------------------


class Scheduler:
    """Checks every rule once per tick in a daemon thread."""

    def __init__(self, config_dir: str | Path | None = None, tick_s: float = TICK_S,
                 start_run: Any = None, clock: Any = None) -> None:
        self.config_dir = config_dir
        self.tick_s = tick_s
        self._start_run = start_run
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="trigger-scheduler", daemon=True)
        self._thread.start()
        logger.info("Trigger scheduler started (every %.0fs)", self.tick_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the loop must outlive one bad tick
                logger.exception("Trigger scheduler tick failed")
            self._stop.wait(self.tick_s)

    # one pass
    def tick(self) -> list[dict[str, Any]]:
        now = self._clock()
        decisions: list[dict[str, Any]] = []
        for p in load_plans(self.config_dir):
            try:
                if p.trigger.source == SCHEDULE:
                    decisions += self._schedule(p, now)
                elif p.trigger.source == RUN:
                    decisions += self._after_run(p, now)
                elif p.trigger.source == STUCK:
                    decisions += self._stuck(p, now)
            except Exception as exc:  # noqa: BLE001 - one rule must not stop the others
                logger.warning("Trigger %s failed this tick: %s", p.trigger.name, exc)
        return decisions

    def _fire(self, p: Plan, key: str, event: dict[str, Any]) -> dict[str, Any] | None:
        fire_id = claim(p.trigger.name, key)
        if fire_id is None:
            return None
        decision: dict[str, Any] = {"trigger": p.trigger.name, "key": key}
        try:
            inputs = render_inputs(p.trigger, event)
            start = self._start_run
            if start is None:
                from temper_ai.api.routes import RunRequest, start_run

                response = start_run(RunRequest(workflow=p.trigger.workflow, inputs=inputs))
                execution_id = response.execution_id
            else:
                execution_id = start(p.trigger.workflow, inputs)
            settle(fire_id, "started", f"{p.trigger.workflow} {execution_id[:8]}", execution_id)
            decision.update(outcome="started", execution_id=execution_id)
            logger.info("Trigger %s started %s %s (%s)", p.trigger.name, p.trigger.workflow, execution_id[:8], key)
        except Exception as exc:  # noqa: BLE001
            detail = str(getattr(exc, "detail", None) or exc)
            settle(fire_id, "failed", detail)
            decision.update(outcome="failed", detail=detail)
            logger.warning("Trigger %s could not start %s: %s", p.trigger.name, p.trigger.workflow, detail)
        return decision

    def _skip(self, p: Plan, key: str, reason: str) -> dict[str, Any] | None:
        if claim(p.trigger.name, key, outcome="skipped", detail=reason) is None:
            return None
        logger.info("Trigger %s skipped %s: %s", p.trigger.name, key, reason)
        return {"trigger": p.trigger.name, "key": key, "outcome": "skipped", "detail": reason}

    def _schedule(self, p: Plan, now: datetime) -> list[dict[str, Any]]:
        name = p.trigger.name
        first_seen, checked_at = state_for(name, now)
        if checked_at is None:
            # First sight: start the clock now; nothing before it was ever due.
            mark_checked(name, now)
            return []
        due, count = last_due(p, checked_at, now, first_seen)
        mark_checked(name, now)
        if due is None:
            return []
        key = due.isoformat()
        local_due = due.astimezone(p.tz).isoformat()
        out: list[dict[str, Any]] = []
        late = now - due
        if late > GRACE and not p.catch_up:
            earlier = f" (and {count - 1} earlier)" if count > 1 else ""
            d = self._skip(p, key, f"missed: temper was not running at {local_due}{earlier}")
            return [d] if d else []
        going = _still_going(last_started(name))
        if going:
            d = self._skip(p, key, f"previous run {going[:8]} is still going")
            return [d] if d else []
        d = self._fire(p, key, {"due": local_due, "now": now.astimezone(p.tz).isoformat(),
                                "late_seconds": int(late.total_seconds())})
        if d:
            out.append(d)
        return out

    def _after_run(self, p: Plan, now: datetime) -> list[dict[str, Any]]:
        first_seen, _ = state_for(p.trigger.name, now)
        candidates = []
        for run in _runs():
            if run.get("workflow_name") not in p.workflows or run.get("status") not in p.statuses:
                continue
            ended = _parse_time(run.get("end_time")) or _parse_time(run.get("start_time"))
            if ended is None or ended < first_seen:
                continue
            candidates.append(run)
        done = decided(p.trigger.name, [r["id"] for r in candidates])
        out = []
        for run in candidates:
            if run["id"] in done:
                continue
            inputs = _run_inputs(run["id"])
            if any(str(inputs.get(k)) != v for k, v in p.inputs):
                continue
            event = {"run": {
                "id": run["id"], "workflow": run.get("workflow_name"), "status": run.get("status"),
                "inputs": inputs, "end_time": run.get("end_time"),
                "cost_usd": run.get("total_cost_usd"), "duration_seconds": run.get("duration_seconds"),
            }}
            d = self._fire(p, run["id"], event)
            if d:
                out.append(d)
        return out

    def _stuck(self, p: Plan, now: datetime) -> list[dict[str, Any]]:
        assert p.after is not None
        runs = _runs("running") + (_runs("waiting") if p.waiting else [])
        runs = [r for r in runs if not p.workflows or r.get("workflow_name") in p.workflows]
        done = decided(p.trigger.name, [r["id"] for r in runs])
        out = []
        for run in runs:
            if run["id"] in done:
                continue
            last = _last_activity(run["id"]) or _parse_time(run.get("start_time"))
            if last is None or now - last < p.after:
                continue
            idle = int((now - last).total_seconds() // 60)
            event = {"run": {
                "id": run["id"], "workflow": run.get("workflow_name"), "status": run.get("status"),
                "inputs": _run_inputs(run["id"]), "idle_minutes": idle, "last_event_at": last.isoformat(),
            }}
            d = self._fire(p, run["id"], event)
            if d:
                out.append(d)
        return out


_scheduler: Scheduler | None = None


def start_scheduler(config_dir: str | Path | None = None) -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler(config_dir)
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    if _scheduler is not None:
        _scheduler.stop()


def describe(config_dir: str | Path | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every rule of every source, with the next due time for schedules."""
    now = now or datetime.now(UTC)
    rules = []
    for trigger in load_triggers(config_dir):
        entry: dict[str, Any] = {"name": trigger.name, "source": trigger.source, "workflow": trigger.workflow,
                                 "enabled": trigger.enabled, "on": trigger.on}
        if trigger.source in SOURCES:
            try:
                p = plan(trigger)
                if trigger.source == SCHEDULE:
                    first_seen = now
                    try:
                        first_seen, _ = state_for(trigger.name, now)
                    except Exception:  # noqa: BLE001, S110 - no database: describe from now
                        pass
                    nxt = next_due(p, now, first_seen)
                    entry["next_due"] = nxt.astimezone(p.tz).isoformat() if nxt else None
            except TriggerConfigError as exc:
                entry["error"] = str(exc)
        rules.append(entry)
    return rules
