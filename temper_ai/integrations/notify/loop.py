"""The notify loop: finds what is worth saying about runs and sends it to
each place the settings name.

Checked every ``TICK_S`` in a daemon thread, from the database, so runs in
worker processes are seen the same as in-process ones. Occasions:

* a question: a gate is waiting (its questions, and Approve / Reject);
* stuck: a running run has written no event for ``stuck_after`` -- or for
  the ``quiet_after`` its own workflow sets, since a long silence is normal
  in a build and alarming in a one-minute run;
* failed / finished: a run ended.

Each occasion in each place is one ``notify_copies`` row, claimed before
it is sent, so a restart never sends anything twice. A run that gates
again after a restart (a new waiting event for the same step) moves its
open copies onto the new wait instead of asking again. Only occasions
after the notify layer first ran count: switching it on replays nothing.

Where a notice goes is :meth:`NotifyConfig.route`: the run's own
settings, then its workflow file's ``notify:``, then the shared file,
with ``origin`` meaning back where the run was started from. When that
comes to nothing, the kind's fallback is used.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from temper_ai.integrations.notify import store
from temper_ai.integrations.notify.config import (
    ORIGIN,
    Block,
    ConfigWatcher,
    NotifyConfig,
    NotifyConfigError,
    parse_block,
)
from temper_ai.integrations.notify.notice import Copy, Decision, Notice, Sender
from temper_ai.runner import quiet

logger = logging.getLogger(__name__)

TICK_S = 15.0
STATE_NAME = "notify"
# Runs temper itself starts to answer people: never worth a notice.
QUIET_WORKFLOWS = frozenset({"slack_pick", "repo_answer", "telegram_pick"})
FAILED_STATES = ("failed", "interrupted")
FINISHED_STATES = ("completed", "cancelled")
ENDED = FAILED_STATES + FINISHED_STATES
# A gate or run older than switching notify on by more than this is history.
LOOKBACK = timedelta(minutes=2)
# A restart marks every unfinished run "interrupted"; the ones parked on a
# question are resumed a moment later. Only a run still interrupted this long
# after it was first seen that way has really failed.
INTERRUPTED_GRACE = timedelta(minutes=5)
WORKFLOW_CACHE_S = 60.0


def _aware(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def question_notice(cfg: NotifyConfig, execution_id: str, workflow: str, event: dict[str, Any],
                    nudged_after_min: int = 0) -> Notice:
    """A waiting gate's event (``{id, data}``) as a question notice."""
    data = event.get("data") or {}
    gate_context = data.get("gate_context") or {}
    return Notice(kind="question", execution_id=execution_id, workflow=workflow,
                  url=cfg.run_url(execution_id), node=str(data.get("name") or ""),
                  event_id=str(event.get("id") or ""), upstream=list(gate_context.get("upstream") or []),
                  questions=list(gate_context.get("questions") or []), nudged_after_min=nudged_after_min)


def who_stopped(execution_id: str) -> str:
    """"Stopped in Telegram by Shine" when someone stopped (or rejected)
    the run from a chat, else "" -- a cancelled run otherwise reads like a
    breakdown."""
    found: list[tuple[datetime, str]] = []
    verbs = {"stop": "Stopped", "reject": "Rejected"}
    try:
        from temper_ai.integrations.slack import store as slack_store

        for act in slack_store.actions(limit=20, execution_id=execution_id):
            if act["action"] in verbs:
                found.append((_aware(act.get("at")) or datetime.min.replace(tzinfo=UTC),
                              f"{verbs[act['action']]} in Slack by {act.get('user_name') or act.get('user_id')}"))
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: no Slack actions for %s: %s", execution_id[:8], exc)
    try:
        from temper_ai.integrations.telegram import store as tg_store

        for act in tg_store.actions(limit=20, execution_id=execution_id):
            if act["action"] in verbs:
                found.append((_aware(act.get("at")) or datetime.min.replace(tzinfo=UTC),
                              f"{verbs[act['action']]} in Telegram by {act.get('user_name') or act.get('user_id')}"))
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify: no Telegram actions for %s: %s", execution_id[:8], exc)
    return max(found)[1] if found else ""


class Notifier:
    def __init__(self, config: ConfigWatcher | None = None, ops: Any = None,
                 clock: Callable[[], datetime] | None = None, tick_s: float = TICK_S) -> None:
        if ops is None:
            from temper_ai.integrations.slack.ops import TemperOps

            ops = TemperOps()
        self.config = config or ConfigWatcher()
        self.ops = ops
        self.tick_s = tick_s
        self.senders: dict[str, Sender] = {}
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick_lock = threading.Lock()
        self._workflow_blocks: dict[str, tuple[float, Block | None]] = {}
        self._migrated = False
        self._interrupted_at: dict[str, datetime] = {}
        self.last_tick_at: str | None = None
        self.last_error: str | None = None
        self.sent = 0
        self.held = 0

    # -- senders -------------------------------------------------------------------

    def register(self, sender: Sender) -> None:
        self.senders[sender.via] = sender

    def unregister(self, via: str) -> None:
        self.senders.pop(via, None)

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="notify-loop", daemon=True)
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
                logger.exception("notify: tick failed")
            self._stop.wait(self.tick_s)

    # -- settings --------------------------------------------------------------------

    def workflow_block(self, workflow: str) -> Block | None:
        """The ``notify:`` block of a workflow's file (cached for a minute)."""
        if not workflow:
            return None
        cached = self._workflow_blocks.get(workflow)
        if cached and time.monotonic() - cached[0] < WORKFLOW_CACHE_S:
            return cached[1]
        block: Block | None = None
        try:
            from sqlmodel import select

            from temper_ai.config.models import Config
            from temper_ai.database import get_session

            with get_session() as session:
                raw = session.exec(select(Config.config).where(Config.type == "workflow",
                                                               Config.name == workflow)).first()
            body = raw.get("workflow", raw) if isinstance(raw, dict) else {}
            if isinstance(body, dict) and body.get("notify") is not None:
                block = parse_block(body["notify"], f"{workflow}: notify")
        except NotifyConfigError as exc:
            logger.warning("notify: %s", exc)
        except Exception as exc:  # noqa: BLE001 - no settings is the safe answer
            logger.debug("notify: could not read %s's settings: %s", workflow, exc)
        self._workflow_blocks[workflow] = (time.monotonic(), block)
        return block

    def run_block(self, execution_id: str) -> Block | None:
        try:
            raw = store.run_settings(execution_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("notify: could not read %s's own settings: %s", execution_id[:8], exc)
            return None
        if raw is None:
            return None
        try:
            return parse_block(raw, "run notify")
        except NotifyConfigError as exc:
            logger.warning("notify: run %s: %s", execution_id[:8], exc)
            return None

    def _blocks(self, workflow: str, execution_id: str) -> tuple[Block | None, Block | None]:
        return self.workflow_block(workflow), self.run_block(execution_id)

    # -- where things go -------------------------------------------------------------

    def _expand(self, cfg: NotifyConfig, items: tuple[str, ...], execution_id: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for item in items:
            if item == ORIGIN:
                for via, sender in list(self.senders.items()):
                    try:
                        found = sender.origins(execution_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("notify: %s origins of %s: %s", via, execution_id[:8], exc)
                        continue
                    out += [(via, sender.canonical(t)) for t in found]
                continue
            place = cfg.places.get(item)
            if place is None:
                logger.warning("notify: no place named %r in %s", item, cfg.path or "the notify config")
                continue
            place_sender = self.senders.get(place.via)
            if place_sender is None:
                logger.info("notify: %s is off, so %s gets nothing", place.via, place.name)
                continue
            try:
                out.append((place.via, place_sender.canonical(place.target)))
            except Exception as exc:  # noqa: BLE001
                logger.warning("notify: can't reach %s: %s", place.describe(), exc)
        seen: set[tuple[str, str]] = set()
        return [t for t in out if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]

    def targets(self, cfg: NotifyConfig, kind: str, workflow: str, execution_id: str) -> list[tuple[str, str]]:
        """[(via, target)] for a ``kind`` notice about this run."""
        if workflow in QUIET_WORKFLOWS:
            return []
        wf_block, run_block = self._blocks(workflow, execution_id)
        route = cfg.route(kind, workflow, wf_block, run_block)
        if not route:
            return []
        out = self._expand(cfg, route, execution_id)
        if not out:
            out = self._expand(cfg, cfg.fallback.get(kind, ()), execution_id)
        return out

    # -- one pass --------------------------------------------------------------------

    def tick(self) -> list[dict[str, Any]]:
        from temper_ai.triggers.scheduler import state_for

        with self._tick_lock:
            now = self._clock()
            self.last_error = None
            cfg = self.config.get()
            if not self._migrated:
                self._migrated = True
                try:
                    migrate_slack_notices()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("notify: moving Slack's open notices over failed: %s", exc)
            runs = {r["id"]: r for r in self.ops.recent() if r.get("id")}
            since = state_for(STATE_NAME, now)[0] - LOOKBACK
            out: list[dict[str, Any]] = []
            steps: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
                ("questions", lambda: self._questions(cfg, now, since, runs)),
                ("answered", lambda: self._close_answered(cfg)),
                ("nudges", lambda: self._nudges(cfg, now, runs)),
                ("ends", lambda: self._ends(cfg, now, since, runs)),
                ("stuck", lambda: self._stuck(cfg, now, since, runs)),
                ("held", lambda: self._release(cfg, now, runs)),
            ]
            for name, step in steps:
                try:
                    out += step()
                except Exception as exc:  # noqa: BLE001 - one kind must not stop the others
                    logger.warning("notify: %s check failed: %s", name, exc, exc_info=True)
                    self.last_error = f"{name}: {exc}"
            self.last_tick_at = now.isoformat(timespec="seconds")
            return out

    def _deliver(self, cfg: NotifyConfig, notice: Notice | Callable[[], Notice], key: str, kind: str,
                 workflow: str, execution_id: str, targets: list[tuple[str, str]], now: datetime, *,
                 node: str = "", event_id: str = "", nudge: bool = False,
                 state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Claim and send one occasion to each target (held in quiet hours)."""
        if not targets:
            return []
        wf_block, run_block = self._blocks(workflow, execution_id)
        # Not the quiet of a quiet run: these are the hours you asked not to
        # be disturbed in. Named apart because the module deciding the other
        # kind of quiet is imported here too, and the two must never be one
        # careless line away from each other.
        quiet_hours = cfg.quiet_hours(workflow, wf_block, run_block)
        hold_until = quiet_hours.holds(kind, now) if quiet_hours else None
        built: Notice | None = notice if isinstance(notice, Notice) else None
        out = []
        for via, target in targets:
            copy = store.claim(key, kind, execution_id, via, target, node=node, event_id=event_id,
                               status="held" if hold_until else "sending", release_at=hold_until,
                               nudge=nudge, state=state, at=now)
            if copy is None:
                continue
            if hold_until:
                self.held += 1
                logger.info("notify: %s notice for %s held until %s (quiet hours)", kind, execution_id[:8],
                            hold_until.isoformat(timespec="minutes"))
                out.append({"kind": kind, "execution_id": execution_id, "via": via, "target": target,
                            "held_until": hold_until.isoformat()})
                continue
            if built is None:
                built = notice() if callable(notice) else notice
            out.append(self._send(copy, built))
        return out

    def _send(self, copy: Copy, notice: Notice) -> dict[str, Any]:
        sender = self.senders.get(copy.via)
        result = {"kind": copy.kind, "execution_id": copy.execution_id, "via": copy.via, "target": copy.target}
        if sender is None:
            store.mark(copy.id, "failed", detail=f"{copy.via} is off")
            return {**result, "error": f"{copy.via} is off"}
        try:
            ref = sender.send(notice, copy.target, copy)
        except Exception as exc:  # noqa: BLE001 - one bad place must not stop the rest
            store.mark(copy.id, "failed", detail=f"{type(exc).__name__}: {exc}")
            logger.warning("notify: could not send the %s notice for %s to %s %s: %s", copy.kind,
                           copy.execution_id[:8], copy.via, copy.target, exc)
            return {**result, "error": str(exc)}
        store.mark(copy.id, "sent", ref=ref)
        self.sent += 1
        logger.info("notify: %s notice for %s %s -> %s %s", copy.kind, notice.workflow, copy.execution_id[:8],
                    copy.via, ref)
        return {**result, "ref": ref}

    # -- questions ---------------------------------------------------------------------

    def _workflow_of(self, execution_id: str, runs: dict[str, dict[str, Any]]) -> str:
        run = runs.get(execution_id)
        if run and run.get("workflow_name"):
            return str(run["workflow_name"])
        try:
            return str(self.ops.summary(execution_id).get("workflow") or "")
        except Exception:  # noqa: BLE001
            return ""

    def question_notice(self, cfg: NotifyConfig, execution_id: str, workflow: str, event: dict[str, Any],
                        nudged_after_min: int = 0) -> Notice:
        return question_notice(cfg, execution_id, workflow, event, nudged_after_min)

    def _questions(self, cfg: NotifyConfig, now: datetime, since: datetime,
                   runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        newest: dict[tuple[str, str], dict[str, Any]] = {}
        for ev in self.ops.waiting_gates():     # newest first
            eid = str(ev.get("execution_id") or "")
            node = str((ev.get("data") or {}).get("name") or "")
            if eid and node:
                newest.setdefault((eid, node), ev)
        out: list[dict[str, Any]] = []
        for (eid, node), ev in newest.items():
            run = runs.get(eid) or {}
            if run.get("status") in ENDED:
                continue
            event_id = str(ev["id"])
            key = f"q:{event_id}"
            # An older wait at this step that nobody answered: the run was
            # resumed after a restart and asks again. Its messages now show
            # this wait. (An answered one is closed, and this is news.)
            older = {c.event_id for c in store.copies(kind="question", execution_id=eid)
                     if c.node == node and c.key != key}
            unanswered = [e for e in older if (self.ops.gate_decision(e) or {}).get("status") == "waiting"]
            moved = store.rekey_question(eid, node, key, event_id, unanswered)
            if moved:
                logger.info("notify: %s asks again at %s; its %d open message(s) now show the new wait",
                            eid[:8], node, moved)
            at = _aware(ev.get("timestamp")) or now
            if at < since and not store.has_copies(key):
                continue
            workflow = self._workflow_of(eid, runs)
            targets = self.targets(cfg, "question", workflow, eid)
            out += self._deliver(cfg, partial(self.question_notice, cfg, eid, workflow, ev), key,
                                 "question", workflow, eid, targets, now, node=node, event_id=event_id)
        return out

    def _close_answered(self, cfg: NotifyConfig) -> list[dict[str, Any]]:
        """Questions answered anywhere (a chat, the dashboard, the API) or
        closed by the run stopping: every copy loses its buttons."""
        by_key: dict[str, list[Copy]] = {}
        for c in store.copies(kind="question"):
            by_key.setdefault(c.key, []).append(c)
        out = []
        for key, group in by_key.items():
            decision = self.ops.gate_decision(group[0].event_id)
            if (decision or {}).get("status") == "waiting":
                continue
            d = Decision.from_event(decision)
            self.close_question(key, d, raw=decision)
            out.append({"kind": "question_closed", "execution_id": group[0].execution_id, "verdict": d.verdict})
        return out

    def close_question(self, key: str, decision: Decision, *, raw: dict[str, Any] | None = None,
                       skip: int | None = None) -> int:
        """Every open copy of question ``key`` loses its buttons and says how
        it was answered. ``raw`` is the gate event (``gate_decision``) if the
        caller has it; ``skip`` is a copy the caller already updated itself.
        Returns how many messages were edited."""
        group = store.copies(key=key)
        if not group:
            return 0
        cfg = self.config.get()
        first = group[0]
        if raw is None:
            raw = self.ops.gate_decision(first.event_id)
        workflow = self._workflow_of(first.execution_id, {})
        notice = self.question_notice(cfg, first.execution_id, workflow,
                                      {"id": first.event_id, "data": (raw or {}).get("data") or {}})
        detail = f"{decision.verdict} {decision.who} {decision.where}".strip()
        edited = 0
        for c in group:
            if c.id == skip:
                store.mark(c.id, "closed", only_from=store.OPEN, detail=detail)
                continue
            if not store.mark(c.id, "closed", only_from=("sent",), detail=detail):
                store.mark(c.id, "closed", only_from=("held", "sending"), detail=f"{detail} (not sent)")
                continue
            sender = self.senders.get(c.via)
            if sender is None:
                continue
            try:
                sender.close_question(c, notice, decision)
                edited += 1
            except Exception as exc:  # noqa: BLE001 - the rest still get closed
                logger.warning("notify: could not close a question of %s in %s: %s", c.execution_id[:8], c.via, exc)
        return edited

    def _nudges(self, cfg: NotifyConfig, now: datetime, runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        first: dict[str, Copy] = {}
        for c in store.copies(kind="question", statuses=("sent",)):
            if c.key not in first or (c.created_at and first[c.key].created_at
                                      and c.created_at < first[c.key].created_at):  # type: ignore[operator]
                first[c.key] = c
        out: list[dict[str, Any]] = []
        for key, c in first.items():
            workflow = self._workflow_of(c.execution_id, runs)
            wf_block, run_block = self._blocks(workflow, c.execution_id)
            nudge = cfg.nudge(workflow, wf_block, run_block)
            if nudge is None or workflow in QUIET_WORKFLOWS or c.created_at is None:
                continue
            if now - c.created_at < nudge.after:
                continue
            targets = self._expand(cfg, nudge.to, c.execution_id)
            if not targets:
                continue
            decision = self.ops.gate_decision(c.event_id)
            if (decision or {}).get("status") != "waiting":
                continue
            ev = {"id": c.event_id, "data": (decision or {}).get("data") or {}}
            minutes = int(nudge.after.total_seconds() // 60)
            out += self._deliver(cfg, partial(self.question_notice, cfg, c.execution_id, workflow, ev,
                                              nudged_after_min=minutes),
                                 key, "question", workflow, c.execution_id, targets, now, node=c.node,
                                 event_id=c.event_id, nudge=True)
        return out

    # -- ends --------------------------------------------------------------------------

    def end_notice(self, cfg: NotifyConfig, execution_id: str, workflow: str) -> Notice:
        summary = self.ops.summary(execution_id)
        status = str(summary.get("status") or "")
        return Notice(kind="failed" if status in FAILED_STATES else "finished", execution_id=execution_id,
                      workflow=str(summary.get("workflow") or workflow), url=cfg.run_url(execution_id),
                      summary=summary, status=status,
                      stopped_by=who_stopped(execution_id) if status == "cancelled" else "")

    def _ends(self, cfg: NotifyConfig, now: datetime, since: datetime,
              runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for gone in [e for e in self._interrupted_at if (runs.get(e) or {}).get("status") != "interrupted"]:
            del self._interrupted_at[gone]
        for run in runs.values():
            status = run.get("status")
            if status not in ENDED:
                continue
            at = _aware(run.get("end_time")) or _aware(run.get("start_time"))
            if at is None or at < since:
                continue
            eid = str(run["id"])
            key = f"end:{eid}@{run.get('end_time') or run.get('start_time')}"
            if store.has_copies(key):
                continue
            if status == "interrupted" and now - self._interrupted_at.setdefault(eid, now) < INTERRUPTED_GRACE:
                continue  # it may be resumed in a moment
            kind = "failed" if status in FAILED_STATES else "finished"
            workflow = str(run.get("workflow_name") or "")
            targets = self.targets(cfg, kind, workflow, eid)
            if not targets:
                # Remember it was looked at, so the list is not built again every tick.
                store.claim(key, kind, eid, "", "", status="closed", state={"reason": "nowhere to send"})
            else:
                out += self._deliver(cfg, partial(self.end_notice, cfg, eid, workflow), key, kind,
                                     workflow, eid, targets, now)
            self._close_stuck(cfg, eid, workflow, str(status))
        return out

    def _close_stuck(self, cfg: NotifyConfig, execution_id: str, workflow: str, status: str) -> None:
        for c in store.copies(kind="stuck", execution_id=execution_id):
            if not store.mark(c.id, "closed", only_from=("sent",)):
                store.mark(c.id, "closed", only_from=("held", "sending"))
                continue
            sender = self.senders.get(c.via)
            if sender is None:
                continue
            notice = Notice(kind="stuck", execution_id=execution_id, workflow=workflow,
                            url=cfg.run_url(execution_id), status=status)
            try:
                sender.close_stuck(c, notice)
            except Exception as exc:  # noqa: BLE001
                logger.warning("notify: could not close a quiet notice of %s in %s: %s", execution_id[:8], c.via, exc)

    # -- stuck ---------------------------------------------------------------------------

    def stuck_notice(self, cfg: NotifyConfig, run: dict[str, Any], last: datetime, now: datetime) -> Notice:
        eid = str(run["id"])
        return Notice(kind="stuck", execution_id=eid, workflow=str(run.get("workflow_name") or ""),
                      url=cfg.run_url(eid), status=str(run.get("status") or ""),
                      idle_min=int((now - last).total_seconds() // 60), last_at=last.isoformat(),
                      active_nodes=self._active_nodes(eid))

    def _stuck(self, cfg: NotifyConfig, now: datetime, since: datetime,
               runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Runs that have gone quiet, one message each.

        The choice itself is :func:`temper_ai.runner.quiet.look`, the same rule
        the run page shows a badge from, so a message never contradicts the
        screen. What stays here is notify's own part: how long counts as quiet
        for this workflow, whether this spell has already been spoken for, and
        where to send it.
        """
        out: list[dict[str, Any]] = []
        for run in runs.values():
            workflow = str(run.get("workflow_name") or "")
            if workflow in QUIET_WORKFLOWS:
                continue
            eid = str(run["id"])
            last = _aware(self.ops.last_activity(eid)) or _aware(run.get("start_time"))
            verdict = quiet.look(
                quiet.Run(
                    execution_id=eid,
                    workflow_name=workflow,
                    status=str(run.get("status") or ""),
                    last_activity_at=last,
                    started_at=_aware(run.get("start_time")),
                    after=quiet.after_for(workflow, cfg.stuck_after),
                ),
                now=now,
                default_after=cfg.stuck_after,
            )
            if not verdict.quiet or last is None:
                continue
            # Quiet since before notify was on: a leftover, not news.
            if last < since - verdict.after:
                continue
            key = f"stuck:{eid}@{last.isoformat(timespec='seconds')}"
            if store.has_copies(key):
                continue
            if self.ops.waiting_gates(execution_id=eid):
                continue   # waiting for an answer is not stuck
            targets = self.targets(cfg, "stuck", workflow, eid)
            if not targets:
                store.claim(key, "stuck", eid, "", "", status="closed", state={"reason": "nowhere to send"})
                continue
            out += self._deliver(cfg, partial(self.stuck_notice, cfg, run, last, now), key, "stuck",
                                 workflow, eid, targets, now, state={"last": last.isoformat()})
        return out

    def _active_nodes(self, execution_id: str) -> list[str]:
        try:
            nodes = self.ops.summary(execution_id).get("nodes") or []
        except Exception:  # noqa: BLE001
            return []
        found: list[str] = []
        stack = list(nodes)
        while stack:
            n = stack.pop(0)
            stack.extend(n.get("child_nodes") or n.get("children") or [])
            if n.get("status") == "running":
                found.append(str(n.get("name")))
        return found[:5]

    # -- held for quiet hours ------------------------------------------------------------

    def _release(self, cfg: NotifyConfig, now: datetime, runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for c in store.due_held(now):
            if not store.mark(c.id, "sending", only_from=("held",)):
                continue
            workflow = self._workflow_of(c.execution_id, runs)
            notice: Notice | None = None
            try:
                if c.kind == "question":
                    decision = self.ops.gate_decision(c.event_id)
                    if (decision or {}).get("status") == "waiting":
                        notice = self.question_notice(cfg, c.execution_id, workflow,
                                                      {"id": c.event_id, "data": (decision or {}).get("data") or {}})
                elif c.kind == "stuck":
                    run = runs.get(c.execution_id) or {}
                    last = _aware(c.state.get("last"))
                    if run.get("status") == "running" and last is not None:
                        notice = self.stuck_notice(cfg, run, last, now)
                else:
                    notice = self.end_notice(cfg, c.execution_id, workflow)
            except Exception as exc:  # noqa: BLE001
                store.mark(c.id, "failed", detail=f"rebuilding after quiet hours: {exc}")
                continue
            if notice is None:
                store.mark(c.id, "closed", detail="over before quiet hours ended")
                continue
            out.append(self._send(c, notice))
        return out


def migrate_slack_notices() -> int:
    """Slack's own notices from before the notify layer (``trigger_fires``
    rows ``slack:gate`` / ``slack:stuck`` / ``slack:end``) become copies, so
    an old question still loses its buttons when answered and an old
    ending is not announced twice. Runs once per process; idempotent."""
    from sqlmodel import col, select

    from temper_ai.database import get_session
    from temper_ai.triggers.models import TriggerFire

    moved = 0
    with get_session() as session:
        rows = session.exec(select(TriggerFire).where(
            col(TriggerFire.trigger).in_(["slack:gate", "slack:stuck", "slack:end"]),
            col(TriggerFire.outcome).in_(["posted", "posting"])).order_by(col(TriggerFire.id).desc())
            .limit(500)).all()
        items = [(r.id, r.trigger, r.key, r.detail, r.execution_id) for r in rows]
    for fire_id, trigger, key, detail, execution_id in items:
        eid = str(execution_id or key.split("@")[0])
        pairs = [p for p in (detail or "").split(",") if ":" in p]
        node, event_id = "", ""
        if trigger == "slack:gate":
            kind, new_key, event_id = "question", f"q:{key}", key
            try:
                from temper_ai.integrations.slack.ops import TemperOps

                decision = TemperOps().gate_decision(key) or {}
                node = str((decision.get("data") or {}).get("name") or "")
            except Exception:  # noqa: BLE001
                pass
        elif trigger == "slack:stuck":
            kind, new_key = "stuck", f"stuck:{key}"
        else:
            kind, new_key = "finished", f"end:{key}"
        for pair in pairs:
            channel, _, ts = pair.partition(":")
            copy = store.claim(new_key, kind, eid, "slack", channel, node=node, event_id=event_id,
                               status="sent" if kind != "finished" else "closed")
            if copy is not None:
                store.mark(copy.id, ref=f"{channel}:{ts}")
                moved += 1
        with get_session() as session:
            row = session.get(TriggerFire, fire_id)
            if row is not None:
                row.outcome = "moved"
                session.add(row)
                session.commit()
    if moved:
        logger.info("notify: moved %d open Slack notice(s) over", moved)
    return moved
