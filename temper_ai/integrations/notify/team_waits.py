"""Fixed alerts for the waits a free-flowing team asks its owner (notice kind ``team_wait``).

A free-flowing team (FLOW, docs/pi-team-messages.md) asks its owner on the Team page: a
member's question, a $100 spending check-in, whether to restart after a weekly limit, and now
and then another decision. Each asked wait is also a waiting gate event, which the ordinary
``question`` notice would show with the member's own words and Approve / Reject buttons. For a
FLOW team run, this module replaces that notice with a fixed alert: one sentence naming the
kind of wait, and a link to the run's Team page. Nothing a member wrote goes into the alert,
its closing edit or the ``notify_copies`` row.

Which waits get an alert is the Team page's own rule (``open_waits_view`` with ``flow=True``,
asked waits only), so the alert and the page never disagree: a five-hour limit resumes by
itself and asks nothing; a check-in is not asked while running work finishes; a closed wait
or an ended team asks nothing.

Read only: it never answers, resumes, retries or changes a run. With the Pi step switched off
(or no Pi tables yet) it looks at nothing: no alert is sent or closed, every gate goes the
ordinary way, and nothing past ``temper_ai.pi_agent``'s switch is imported. It never makes a
table. Any failure to read makes the whole scan "failed": the loop then sends no alert,
closes none, and leaves every step-wait gate out of the ordinary questions, so a read error
can't turn into a message with a member's words in it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

KIND = "team_wait"
KEY_PREFIX = "tw:"
#: The fixed reasons, by the kind the Team page shows. Nothing else is ever said.
REASONS = {
    "question": "a member's question",
    "pause": "a spending check-in",
    "limit": "a usage-limit restart decision",
}
OTHER_REASON = "an owner decision"
#: The places a team alert can go: Slack only, until a Telegram rendering of the same fixed
#: alert is built and tested.
VIAS = ("slack",)


def reason_for(shown_kind: str) -> str:
    """The fixed reason for a wait the Team page shows as ``shown_kind``."""
    return REASONS.get(shown_kind, OTHER_REASON)


def alert_text(reason: str) -> str:
    return f"The team is waiting for you: {reason}. Answer on the Team page."


def closed_text(reason: str) -> str:
    return f"No longer waiting for you: {reason}."


def team_url(dashboard_url: str, execution_id: str) -> str:
    base = (dashboard_url or "").rstrip("/")
    return f"{base}/app/team/runs/{execution_id}" if base else ""


def wait_of(key: str, state: dict[str, Any] | None = None) -> str:
    """The wait id a ``team_wait`` copy is about."""
    return str((state or {}).get("wait_id") or key.removeprefix(KEY_PREFIX))


@dataclass(frozen=True)
class TeamAlert:
    """One wait the Team page asks the owner to answer now."""

    execution_id: str
    wait_id: str
    event_id: str
    reason: str
    url: str
    asked_at: datetime | None = None

    @property
    def key(self) -> str:
        return f"{KEY_PREFIX}{self.wait_id}"

    @property
    def state(self) -> dict[str, Any]:
        """What the copy row keeps: ids, the fixed reason and the link. No member text."""
        return {"wait_id": self.wait_id, "reason": self.reason, "url": self.url}


@dataclass
class TeamScan:
    """One look at the free-flowing teams with something waiting."""

    alerts: list[TeamAlert] = field(default_factory=list)
    #: every open wait of the FLOW teams looked at that are still going
    open_waits: set[str] = field(default_factory=set)
    #: waiting gate events at a FLOW team's step: never an ordinary question
    flow_events: set[str] = field(default_factory=set)
    #: False when nothing was looked at (the Pi step is off, or there are no Pi tables)
    on: bool = True
    failed: bool = False

    @property
    def settled(self) -> bool:
        """True when the teams were read: only then are alerts sent, released or closed."""
        return self.on and not self.failed

    def skips(self, event: dict[str, Any]) -> bool:
        """True when the ordinary question path must leave this waiting gate event alone."""
        if str(event.get("id") or "") in self.flow_events:
            return True
        return self.failed and bool((event.get("data") or {}).get("step_wait"))


def switched_on() -> bool:
    """Whether the Pi step is on (``TEMPER_PI_AGENT``): only then are teams looked at."""
    from temper_ai import pi_agent

    return pi_agent.enabled()


def _aware(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def scan(gates: Iterable[dict[str, Any]], runs: dict[str, dict[str, Any]], dashboard_url: str,
         also: Iterable[str] = ()) -> TeamScan:
    """The FLOW team waits to alert about, from the waiting gate events (``gates``, as
    ``TemperOps.waiting_gates`` gives them), the recent runs (``runs``, by id) and the runs
    with an open alert (``also``)."""
    if not switched_on():
        return TeamScan(on=False)
    try:
        return _scan(list(gates), runs, dashboard_url, set(also))
    except Exception as exc:  # noqa: BLE001 - fail closed: no alert, no close, no member text
        logger.warning("notify: could not read the team waits: %s", exc, exc_info=True)
        return TeamScan(failed=True)


def _team_of(ledger: Any, execution_id: str, workflow: str) -> tuple[dict, str, bool] | None:
    """(trial record, team host path, ended) of a team run, found the Team page's way; None
    for a run that isn't a team trial."""
    from temper_ai.pi_agent import team_trials
    from temper_ai.pi_agent.team_config import trial_id_of

    trial = team_trials.find(ledger, execution_id=execution_id)
    outcomes = ledger.outcomes_of(execution_id)
    if trial is None:
        tid = next((o["trial_id"] for o in outcomes if o.get("trial_id")), None)
        tid = tid or trial_id_of(workflow or None)
        trial = team_trials.find(ledger, trial_id=tid) if tid else None
    if trial is None:
        return None
    outcome = outcomes[0] if outcomes else None
    host_path = outcome["host_path"] if outcome else f"{team_trials.TRIAL_STAGE}.team"
    return trial.get("trial") or {}, host_path, bool(outcome and outcome.get("decision"))


def _scan(gates: list[dict[str, Any]], runs: dict[str, dict[str, Any]], dashboard_url: str,
          also: set[str]) -> TeamScan:
    import sqlalchemy as sa

    from temper_ai.database import get_database

    engine = get_database().engine
    found = sa.inspect(engine)
    if not (found.has_table("pi_waits") and found.has_table("pi_team_trials")):
        return TeamScan(on=False)

    from temper_ai.pi_agent.flow_view import run_kind
    from temper_ai.pi_agent.ledger import Ledger
    from temper_ai.pi_agent.team_view import RUN_ENDED, TeamReader, open_waits_view
    from temper_ai.stage.gate import gate_path

    step_waits: dict[str, list[dict[str, Any]]] = {}
    # Oldest first, as the Team page reads them: of two waiting events with one name, the
    # newer counts.
    for ev in sorted(reversed(gates), key=lambda e: _aware(e.get("timestamp")) or datetime.min.replace(tzinfo=UTC)):
        data = ev.get("data") or {}
        eid = str(ev.get("execution_id") or "")
        if eid and data.get("step_wait"):
            step_waits.setdefault(eid, []).append(ev)
    ledger = Ledger(engine)
    out = TeamScan()
    for eid in sorted(set(step_waits) | also):
        run = runs.get(eid) or {}
        team = _team_of(ledger, eid, str(run.get("workflow_name") or ""))
        if team is None:
            continue
        record, host_path, decided = team
        reader = TeamReader(ledger, eid, host_path, str(record.get("leader") or ""))
        if run_kind(record, reader._reviews()) != "flow":
            continue
        events = step_waits.get(eid, [])
        # The team's own step: none of its waits is ever an ordinary question, open or not.
        out.flow_events |= {str(ev["id"]) for ev in events
                            if gate_path(ev.get("data") or {}) == host_path}
        if decided or run.get("status") in RUN_ENDED:
            continue
        asked: dict[str, str] = {}
        when: dict[str, datetime | None] = {}
        for ev in events:
            data = ev.get("data") or {}
            for key in (data.get("name"), data.get("gate_path")):
                if key:
                    asked[str(key)] = str(ev["id"])
            when[str(ev["id"])] = _aware(ev.get("timestamp"))
        url = team_url(dashboard_url, eid)
        for row in ledger.open_waits(eid, host_path):
            out.open_waits.add(str(row["wait_id"]))
        for entry in open_waits_view(reader, asked, flow=True):
            if not entry.get("asked"):
                continue
            event_id = str(entry["event_id"])
            out.alerts.append(TeamAlert(execution_id=eid, wait_id=str(entry["wait_id"]),
                                        event_id=event_id, reason=reason_for(str(entry.get("kind") or "")),
                                        url=url, asked_at=when.get(event_id)))
    return out


# --- acknowledgments, for FLOW's measure (C5) -----------------------------------------------

def receipts(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """``{"notices": [{"wait_id", "at", "channel"}]}`` from ``team_wait`` copy rows: one per
    wait, at the earliest time a place acknowledged it (UTC). A copy Slack did not confirm,
    or one never sent, is not a receipt."""
    first: dict[str, tuple[datetime, str]] = {}
    for row in rows:
        if row.get("kind") != KIND:
            continue
        state = row.get("state") or {}
        at = _aware(state.get("acked_at"))
        if at is None:
            continue
        wait_id = wait_of(str(row.get("key") or ""), state)
        if wait_id not in first or at < first[wait_id][0]:
            first[wait_id] = (at, str(row.get("via") or ""))
    notices = [{"wait_id": w, "at": at.astimezone(UTC).isoformat(), "channel": via}
               for w, (at, via) in first.items()]
    return {"notices": sorted(notices, key=lambda n: (n["at"], n["wait_id"]))}


def read_receipts(engine: Any, execution_id: str) -> dict[str, list[dict[str, str]]]:
    """The acknowledged team alerts of one run, read from ``notify_copies`` with ``engine``
    (read only; makes nothing). Raises when there is no such table: never an empty answer
    for a database it could not look in."""
    import sqlalchemy as sa

    from temper_ai.integrations.notify.models import NotifyCopy

    if not sa.inspect(engine).has_table("notify_copies"):
        raise LookupError("no notify_copies table: the notify layer never ran on this database")
    table = NotifyCopy.__table__  # type: ignore[attr-defined]
    with engine.connect() as conn:
        rows = conn.execute(sa.select(table.c.key, table.c.kind, table.c.via, table.c.state).where(
            table.c.kind == KIND, table.c.execution_id == execution_id)).mappings().all()
    return receipts(dict(r) for r in rows)
