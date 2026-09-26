"""Slack notices about runs: a gate is waiting, a run is stuck, a run ended.

Checked every ``TICK_S`` in a daemon thread, from the database, so runs in
worker processes are seen the same as in-process ones. Each notice is one
occasion, claimed in the trigger scheduler's ``trigger_fires`` table under a
pseudo-rule name, so a restart never sends it twice:

* ``slack:gate``  keyed by the gate's waiting event (a loop that gates the
  same node again is a new wait, and a new notice);
* ``slack:stuck`` keyed by run and its last event (quiet again later is a
  new occasion);
* ``slack:end``   keyed by run and its end time (a resumed run that ends
  again is a new occasion).

Only occasions after Slack was first turned on count: switching it on does
not replay history.

Every notice about a run goes into that run's thread, one per destination
(see ``RunPoster``). A gate message whose gate is answered somewhere else,
in the dashboard say, gets its buttons replaced by the answer.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import col, select

from temper_ai.integrations.slack import blocks, store
from temper_ai.integrations.slack.client import SlackClient, SlackError
from temper_ai.integrations.slack.config import ConfigWatcher, SlackConfig
from temper_ai.integrations.slack.ops import TemperOps

logger = logging.getLogger(__name__)

TICK_S = 15.0
GATE, STUCK, END = "slack:gate", "slack:stuck", "slack:end"
# Runs Slack itself starts to answer people: never worth a notice.
QUIET_WORKFLOWS = frozenset({"slack_pick"})
FAILED_STATES = ("failed", "interrupted")
FINISHED_STATES = ("completed", "cancelled")
# A gate or run older than switching Slack on by more than this is history.
LOOKBACK = timedelta(minutes=2)


def _aware(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class RunPoster:
    """Posts into a run's thread in each destination, starting it if need be."""

    def __init__(self, client: SlackClient) -> None:
        self.client = client
        self._resolved: dict[str, str] = {}
        self._lock = threading.Lock()

    def channel(self, target: str) -> str:
        with self._lock:
            if target in self._resolved:
                return self._resolved[target]
        channel = self.client.resolve(target)
        with self._lock:
            self._resolved[target] = channel
        return channel

    def post(self, execution_id: str, targets: Iterable[str], message: dict[str, Any],
             broadcast: bool = False) -> tuple[list[tuple[str, str]], list[str]]:
        """Post ``message`` to each target; returns ([(channel, ts)], [errors])."""
        posted: list[tuple[str, str]] = []
        errors: list[str] = []
        seen: set[str] = set()
        for target in targets:
            try:
                channel = self.channel(target)
                if channel in seen:
                    continue
                seen.add(channel)
                thread = store.thread_for(execution_id, channel)
                answer = self.client.post(channel, message["text"], message.get("blocks"),
                                          thread_ts=thread, broadcast=broadcast)
                ts = str(answer.get("ts") or "")
                if not thread and ts:
                    store.save_thread(execution_id, channel, ts)
                posted.append((channel, ts))
            except Exception as exc:  # noqa: BLE001 - one bad destination must not stop the rest
                errors.append(f"{target}: {exc}")
                logger.warning("Slack: could not post about %s to %s: %s", execution_id[:8], target, exc)
        return posted, errors


def close_gate(client: SlackClient, event_id: str, where: str | None, message: dict[str, Any],
               line: str, verdict: str, clicked: tuple[str, str] | None = None) -> None:
    """Replace a gate message's buttons with how it was answered, everywhere
    it was posted, and mark its notice closed.

    ``where`` is the notice's "channel:ts,channel:ts"; None looks it up.
    ``clicked`` is the copy a button was pressed on, updated in any case.
    """
    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerFire

    with get_session() as session:
        row = session.exec(select(TriggerFire).where(TriggerFire.trigger == GATE,
                                                     TriggerFire.key == str(event_id))).first()
        if row is not None:
            if where is None:
                where = row.detail if row.outcome == "posted" else ""
            row.outcome, row.detail = "closed", f"{verdict} {row.detail}"[:500]
            session.add(row)
            session.commit()
    pairs = [p for p in (where or "").split(",") if ":" in p]
    if clicked and f"{clicked[0]}:{clicked[1]}" not in pairs:
        pairs.append(f"{clicked[0]}:{clicked[1]}")
    for pair in pairs:
        channel, _, ts = pair.partition(":")
        try:
            client.update(channel, ts, f"{message['text']} ({verdict})",
                          blocks.decided(message.get("blocks"), line, verdict))
        except SlackError as exc:
            logger.warning("Slack: could not close gate message %s/%s: %s", channel, ts, exc)


def close_stuck(client: SlackClient, execution_id: str, workflow: str, status: str, url: str = "") -> None:
    """A run that ended takes the Stop button off its "quiet" notices: they
    would otherwise go on offering to stop a run that is over."""
    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerFire

    with get_session() as session:
        rows = session.exec(select(TriggerFire).where(
            TriggerFire.trigger == STUCK, col(TriggerFire.key).startswith(f"{execution_id}@"),
            TriggerFire.outcome == "posted")).all()
        pairs = [p for row in rows for p in (row.detail or "").split(",") if ":" in p]
        for row in rows:
            row.outcome = "closed"
            session.add(row)
        session.commit()
    if not pairs:
        return
    emoji = blocks.STATUS_EMOJI.get(status, ":grey_question:")
    # "ended (cancelled)", not "ended cancelled": reads right for every status (QA, 2026-09-26).
    text = f"{workflow} ({blocks.short(execution_id)}) went quiet, then ended ({status})"
    body = [blocks.section(f"{emoji} {blocks.run_header(workflow, execution_id, url)} went quiet for a "
                           f"while; it has since ended (*{blocks.esc(status)}*).")]
    for pair in pairs:
        channel, _, ts = pair.partition(":")
        try:
            client.update(channel, ts, text, body)
        except SlackError as exc:
            logger.warning("Slack: could not close quiet notice %s/%s: %s", channel, ts, exc)


STOP_VERBS = {"stop": "Stopped", "reject": "Rejected"}


def stopped_by(execution_id: str) -> str:
    """"Stopped in Slack by @x" when someone stopped (or rejected) the run
    from Slack, else "" -- a cancelled run otherwise reads like a breakdown."""
    try:
        for act in store.actions(limit=20, execution_id=execution_id):
            verb = STOP_VERBS.get(act["action"])
            if verb:
                return f"{verb} in Slack by <@{act['user_id']}>"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Slack: could not look up who stopped %s: %s", execution_id[:8], exc)
    return ""


def targets_for(cfg: SlackConfig, kind: str, run: dict[str, Any], execution_id: str) -> list[str]:
    """Where a notice goes: the configured route, plus where the run was started from Slack."""
    dest = cfg.route(kind, run.get("workflow_name"))
    out = list(dest.channels) + list(dest.users)
    out += [channel for channel, _ in store.threads_of(execution_id, origin_only=True)]
    return out


class Notifier:
    def __init__(self, poster: RunPoster, config: ConfigWatcher, ops: TemperOps | None = None,
                 clock: Callable[[], datetime] | None = None, tick_s: float = TICK_S) -> None:
        self.poster = poster
        self.config = config
        self.ops = ops or TemperOps()
        self.tick_s = tick_s
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_tick_at: str | None = None
        self.last_error: str | None = None
        self.sent = 0

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="slack-notifier", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the loop must outlive one bad tick
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Slack notifier tick failed")
            self._stop.wait(self.tick_s)

    # -- one pass ---------------------------------------------------------------

    def tick(self) -> list[dict[str, Any]]:
        from temper_ai.triggers.scheduler import state_for

        now = self._clock()
        self.last_error = None
        cfg = self.config.get()
        runs = {r["id"]: r for r in self.ops.recent() if r.get("id")}
        out: list[dict[str, Any]] = []
        for name, check in ((GATE, self._gates), (END, self._ends), (STUCK, self._stuck)):
            since = state_for(name, now)[0] - LOOKBACK
            try:
                out += check(cfg, now, since, runs)
            except Exception as exc:  # noqa: BLE001 - one kind must not stop the others
                logger.warning("Slack notifier: %s check failed: %s", name, exc)
                self.last_error = f"{name}: {exc}"
        self.last_tick_at = now.isoformat(timespec="seconds")
        return out

    def _send(self, name: str, key: str, kind: str, run: dict[str, Any], execution_id: str,
              make: Callable[[], dict[str, Any]], cfg: SlackConfig, broadcast: bool) -> dict[str, Any] | None:
        from temper_ai.triggers.scheduler import claim, settle

        workflow = run.get("workflow_name") or ""
        targets = [] if workflow in QUIET_WORKFLOWS else targets_for(cfg, kind, run, execution_id)
        fire_id = claim(name, key, outcome="posting" if targets else "off",
                        detail="" if targets else f"no destination for {kind}")
        if fire_id is None or not targets:
            return None
        posted, errors = self.poster.post(execution_id, targets, make(), broadcast=broadcast)
        where = ",".join(f"{c}:{ts}" for c, ts in posted)
        settle(fire_id, "posted" if posted else "failed", where if posted else "; ".join(errors),
               execution_id=execution_id)
        self.sent += len(posted)
        logger.info("Slack: %s notice for %s %s -> %s", kind, workflow, execution_id[:8], where or errors)
        return {"kind": kind, "execution_id": execution_id, "posted": posted, "errors": errors}

    # gates

    def _gates(self, cfg: SlackConfig, now: datetime, since: datetime,
               runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        from temper_ai.triggers.scheduler import decided

        out: list[dict[str, Any]] = []
        waiting = [e for e in self.ops.waiting_gates()
                   if (_aware(e.get("timestamp")) or now) >= since and e.get("execution_id")]
        done = decided(GATE, [str(e["id"]) for e in waiting])
        for ev in waiting:
            if str(ev["id"]) in done:
                continue
            execution_id = str(ev["execution_id"])
            run = runs.get(execution_id) or {"id": execution_id, "workflow_name": self._workflow_of(execution_id)}
            node = str((ev.get("data") or {}).get("name") or "")
            gate_context = (ev.get("data") or {}).get("gate_context") or {}
            info = {"node_name": node, "event_id": ev["id"], "upstream": gate_context.get("upstream") or [],
                    "questions": gate_context.get("questions") or []}
            summary = {"id": execution_id, "workflow": run.get("workflow_name")}

            def gate_message(s: dict[str, Any] = summary, i: dict[str, Any] = info) -> dict[str, Any]:
                return blocks.gate(s, i, cfg.run_url(s["id"]))

            d = self._send(GATE, str(ev["id"]), "gate", run, execution_id, gate_message, cfg, broadcast=True)
            if d:
                out.append(d)
        out += self._close_answered_gates()
        return out

    def _workflow_of(self, execution_id: str) -> str:
        try:
            return str(self.ops.summary(execution_id).get("workflow") or "")
        except Exception:  # noqa: BLE001
            return ""

    def _close_answered_gates(self) -> list[dict[str, Any]]:
        """Gate messages whose wait was answered outside Slack: buttons off.

        An answer given in Slack closes its own message (``close_gate``), so
        only the dashboard, the API or a cancelled run are left for here.
        """
        from temper_ai.database import get_session
        from temper_ai.triggers.models import TriggerFire

        with get_session() as session:
            rows = session.exec(
                select(TriggerFire).where(TriggerFire.trigger == GATE, TriggerFire.outcome == "posted")
                .order_by(col(TriggerFire.id).desc()).limit(50)
            ).all()
            open_gates = [(r.key, r.detail, r.execution_id) for r in rows]
        out = []
        for event_id, where, execution_id in open_gates:
            decision = self.ops.gate_decision(event_id)
            if (decision or {}).get("status") == "waiting":
                continue
            data = (decision or {}).get("data") or {}
            verdict = str(data.get("gate_status") or (decision or {}).get("status") or "gone")
            line = {"approved": ":white_check_mark: Approved in temper",
                    "rejected": ":no_entry: Rejected in temper"}.get(verdict, f":information_source: Closed ({verdict})")
            reason = ((data.get("gate_response") or {}).get("text") or "") if isinstance(
                data.get("gate_response"), dict) else ""
            if reason:
                line += f": {blocks.esc(blocks.clip(reason, 300))}"
            eid = execution_id or ""
            info = {"node_name": data.get("name") or "", "event_id": event_id,
                    "upstream": (data.get("gate_context") or {}).get("upstream") or [],
                    "questions": (data.get("gate_context") or {}).get("questions") or []}
            message = blocks.gate({"id": eid, "workflow": self._workflow_of(eid)}, info,
                                  self.config.get().run_url(eid))
            close_gate(self.poster.client, event_id, where, message, line, verdict)
            out.append({"kind": "gate_closed", "execution_id": execution_id, "verdict": verdict})
        return out

    # ends

    def _ends(self, cfg: SlackConfig, now: datetime, since: datetime,
              runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        from temper_ai.triggers.scheduler import decided

        ended = []
        for run in runs.values():
            status = run.get("status")
            if status not in FAILED_STATES + FINISHED_STATES:
                continue
            at = _aware(run.get("end_time")) or _aware(run.get("start_time"))
            if at is None or at < since:
                continue
            ended.append((f"{run['id']}@{run.get('end_time') or run.get('start_time')}", run))
        done = decided(END, [k for k, _ in ended])
        out = []
        for key, run in ended:
            if key in done:
                continue
            kind = "failed" if run.get("status") in FAILED_STATES else "finished"
            execution_id = str(run["id"])

            def make(eid: str = execution_id) -> dict[str, Any]:
                summary = self.ops.summary(eid)
                if summary.get("status") == "cancelled":
                    summary["stopped_by"] = stopped_by(eid)
                return blocks.ended(summary, cfg.run_url(eid))

            d = self._send(END, key, kind, run, execution_id, make, cfg, broadcast=(kind == "failed"))
            if d:
                out.append(d)
            close_stuck(self.poster.client, execution_id, str(run.get("workflow_name") or "?"),
                        str(run.get("status")), cfg.run_url(execution_id))
        return out

    # stuck

    def _stuck(self, cfg: SlackConfig, now: datetime, since: datetime,
               runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        from temper_ai.triggers.scheduler import decided

        quiet = []
        for run in runs.values():
            if run.get("status") != "running" or run.get("workflow_name") in QUIET_WORKFLOWS:
                continue
            last = _aware(self.ops.last_activity(run["id"])) or _aware(run.get("start_time"))
            # Quiet since before Slack was on: a leftover, not news.
            if last is None or now - last < cfg.stuck_after or last < since - cfg.stuck_after:
                continue
            quiet.append((f"{run['id']}@{last.isoformat(timespec='seconds')}", run, last))
        done = decided(STUCK, [k for k, _, _ in quiet])
        out = []
        for key, run, last in quiet:
            if key in done:
                continue
            execution_id = str(run["id"])
            idle = int((now - last).total_seconds() // 60)

            since_at: datetime = last

            def make(r: dict[str, Any] = run, i: int = idle, at: datetime = since_at) -> dict[str, Any]:
                return blocks.stuck({"id": r["id"], "workflow": r.get("workflow_name"), "status": r.get("status")},
                                    i, at.isoformat(), self._active_nodes(r["id"]), cfg.run_url(r["id"]))

            d = self._send(STUCK, key, "stuck", run, execution_id, make, cfg, broadcast=True)
            if d:
                out.append(d)
        return out

    def _active_nodes(self, execution_id: str) -> list[str]:
        try:
            nodes = self.ops.summary(execution_id).get("nodes") or []
        except Exception:  # noqa: BLE001
            return []
        return [str(n.get("name")) for n in blocks._walk(nodes) if n.get("status") == "running"][:5]
