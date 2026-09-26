"""Incoming webhooks: an event somewhere else starts a workflow here.

``POST /api/hooks/linear`` is the one address the internet may reach (the
gateway forwards that exact path and nothing else), so it authenticates
itself: the API token cannot be asked of Linear, and instead every delivery
must carry Linear's signature over its exact bytes and be under a minute
old. See triggers.linear.

Linear gives up on a delivery that takes more than five seconds to answer,
and starting a run can take longer than that (loading the workflow,
connecting its MCP servers). So the handler only checks the delivery and
answers; matching rules and starting runs happen after the response, in the
background. What became of each delivery is kept in memory for
``GET /api/hooks/linear/recent`` -- behind the API token like the rest of
the API, and not reachable from the internet -- and in the log.

Linear retries a delivery it thinks failed, with the same
``Linear-Delivery`` id, so ids already handled are remembered and a retry
of one is acknowledged without starting anything twice.

One issue, one run of a workflow at a time. A rule whose inputs name an
``issue_id`` does not start its workflow for an issue whose last run of
that workflow is still going: two runs working one issue would build on the
same branch at once. The skipped event is recorded; the comment it carried
is still in the thread for the next run to read.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from temper_ai.triggers import linear
from temper_ai.triggers.rules import Trigger, load_triggers, render_inputs

logger = logging.getLogger(__name__)

router = APIRouter()

LINEAR_PATH = "/api/hooks/linear"
RECENT_MAX = 50
DELIVERY_MEMORY = 4096
DELIVERY_TTL_S = 24 * 3600.0  # Linear's last retry comes 6 h after the first attempt


class _SeenDeliveries:
    """Delivery ids handled recently, oldest dropped first."""

    def __init__(self, capacity: int = DELIVERY_MEMORY, ttl_s: float = DELIVERY_TTL_S) -> None:
        self._ids: OrderedDict[str, float] = OrderedDict()
        self._capacity = capacity
        self._ttl_s = ttl_s
        self._lock = threading.Lock()

    def first_time(self, delivery: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            while self._ids:
                oldest, seen_at = next(iter(self._ids.items()))
                if now - seen_at <= self._ttl_s and len(self._ids) < self._capacity:
                    break
                self._ids.pop(oldest)
            if delivery in self._ids:
                return False
            self._ids[delivery] = now
            return True

    def clear(self) -> None:
        with self._lock:
            self._ids.clear()


_seen = _SeenDeliveries()
_recent: deque[dict[str, Any]] = deque(maxlen=RECENT_MAX)
_recent_lock = threading.Lock()
# (workflow, issue id) -> the execution id of the last run a rule started for it
_issue_runs: dict[tuple[str, str], str] = {}
_issue_lock = threading.Lock()
_ACTIVE = frozenset({"pending", "queued", "running", "waiting"})


def _record(delivery: str, event: dict[str, Any]) -> dict[str, Any]:
    raw_actor = event.get("actor")
    actor: dict[str, Any] = raw_actor if isinstance(raw_actor, dict) else {}
    record: dict[str, Any] = {
        "delivery": delivery,
        "received_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "type": event.get("type"),
        "action": event.get("action"),
        "url": event.get("url"),
        "actor": actor.get("name") or actor.get("id"),
        "actor_id": actor.get("id"),
        "actor_type": actor.get("type"),
        "outcome": "received",
        "runs": [],
    }
    with _recent_lock:
        _recent.append(record)
    return record


@router.post(LINEAR_PATH)
async def linear_webhook(request: Request, background: BackgroundTasks) -> dict[str, Any]:
    secret = linear.signing_secret()
    if secret is None:
        raise HTTPException(
            status_code=503,
            detail=f"Linear webhooks are off: {linear.SIGNING_SECRET_ENV} is not set.",
        )
    raw = await request.body()
    if not linear.verify_signature(raw, request.headers.get("linear-signature"), secret):
        raise HTTPException(status_code=401, detail="Linear-Signature does not match the body.")
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="The body is not JSON.") from exc
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="The body is not a JSON object.")
    if not linear.is_fresh(event):
        raise HTTPException(status_code=401, detail="webhookTimestamp is more than a minute away.")

    delivery = request.headers.get("linear-delivery", "").strip()
    record = _record(delivery, event)
    if delivery and not _seen.first_time(delivery):
        record["outcome"] = "ignored: this delivery was already received"
        logger.info("Linear delivery %s: a retry of one already handled", delivery)
        return {"ok": True, "delivery": delivery, "duplicate": True}

    background.add_task(dispatch, event, record)
    return {"ok": True, "delivery": delivery}


@router.get(LINEAR_PATH + "/recent")
def linear_recent() -> dict[str, Any]:
    """The last deliveries and what became of each, newest first."""
    with _recent_lock:
        return {"deliveries": [dict(r) for r in reversed(_recent)]}


def dispatch(
    event: dict[str, Any], record: dict[str, Any], config_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Match one verified delivery against the Linear rules and start their workflows."""
    try:
        _dispatch(event, record, config_dir)
    except Exception as exc:  # noqa: BLE001 - a background task has no caller to raise to
        logger.exception("Linear delivery %s failed", record.get("delivery"))
        record["outcome"] = f"error: {exc}"
    logger.info(
        "Linear delivery %s (%s %s): %s",
        record.get("delivery"), record.get("type"), record.get("action"), record["outcome"],
    )
    return record


def _wants_comments(triggers: list[Trigger]) -> bool:
    for trigger in triggers:
        kind = trigger.on.get("type")
        kinds = kind if isinstance(kind, (list, tuple, set)) else [kind]
        if any(str(k).strip().lower() == "comment" for k in kinds if k is not None):
            return True
    return False


def _dispatch(event: dict[str, Any], record: dict[str, Any], config_dir: str | Path | None) -> None:
    triggers = [t for t in load_triggers(config_dir, source=linear.SOURCE) if t.enabled]
    if linear.needs_issue(event) and _wants_comments(triggers):
        # A comment names its issue but not the issue's labels: ask, or match nothing
        # (a rule on labelled issues must not fire for an issue it cannot see).
        try:
            linear.enrich(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read the issue of Linear comment %s: %s", record.get("delivery"), exc)
            record["outcome"] = f"skipped: could not read the comment's issue ({exc})"
            return

    matched: list[Trigger] = []
    for trigger in triggers:
        try:
            if linear.matches(trigger.on, event):
                matched.append(trigger)
        except ValueError as exc:
            logger.warning("Trigger %s (%s): %s", trigger.name, trigger.path, exc)
    if not matched:
        record["outcome"] = "no trigger matched"
        return

    skipped = _drop_own_changes(event, matched)
    if skipped:
        record["outcome"] = skipped
        return

    from temper_ai.api.routes import RunRequest, start_run

    for trigger in matched:
        entry: dict[str, Any] = {"trigger": trigger.name, "workflow": trigger.workflow}
        try:
            inputs = render_inputs(trigger, event)
            issue = str(inputs.get("issue_id") or "").strip()
            key = (trigger.workflow, issue)
            with _issue_lock:
                going = _run_still_going(_issue_runs.get(key)) if issue else None
                if going:
                    entry["skipped"] = f"{trigger.workflow} run {going[:8]} for this issue is still going"
                    record["runs"].append(entry)
                    continue
                response = start_run(RunRequest(workflow=trigger.workflow, inputs=inputs))
                if issue:
                    _issue_runs[key] = response.execution_id
            entry["execution_id"] = response.execution_id
        except HTTPException as exc:
            entry["error"] = str(exc.detail)
        except Exception as exc:  # noqa: BLE001 - one rule failing must not stop the others
            entry["error"] = str(exc)
        record["runs"].append(entry)

    started = [r for r in record["runs"] if "execution_id" in r]
    failed = [r for r in record["runs"] if "error" in r]
    busy = [r for r in record["runs"] if "skipped" in r]
    parts = []
    if started:
        parts.append("started " + ", ".join(f"{r['workflow']} {r['execution_id'][:8]}" for r in started))
    if busy:
        parts.append("skipped " + "; ".join(f"{r['trigger']}: {r['skipped']}" for r in busy))
    if failed:
        parts.append("failed " + "; ".join(f"{r['trigger']}: {r['error']}" for r in failed))
    record["outcome"] = " / ".join(parts)


def _drop_own_changes(event: dict[str, Any], matched: list[Trigger]) -> str | None:
    """Remove the rules that must not fire for this event; a reason if none are left.

    Fails closed: if temper cannot tell whether the change was its own (no
    app configured, or Linear did not answer), a rule that ignores its own
    changes does not fire. A loop costs more than a missed event.
    """
    guarded = [t for t in matched if t.ignore_self]
    if not guarded:
        return None
    reason = None
    try:
        me = linear.app_user_id()
        if me is None:
            reason = (
                f"skipped: {linear.CLIENT_ID_ENV}/{linear.CLIENT_SECRET_ENV} are not set, so "
                "temper cannot tell its own changes apart (set ignore_self: false to fire anyway)"
            )
        elif linear.is_own(event, me):
            reason = "ignored: temper's own change"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not ask Linear who temper's app user is: %s", exc)
        reason = f"skipped: could not ask Linear who temper's app user is ({exc})"
    if reason is None:
        return None
    matched[:] = [t for t in matched if not t.ignore_self]
    return None if matched else reason


def _run_still_going(execution_id: str | None) -> str | None:
    """The id back if that run has not finished yet; None if it has, or is unknown."""
    if not execution_id:
        return None
    from temper_ai.api.routes import _state, get_workflow

    try:
        if execution_id in _state().running:
            return execution_id
    except Exception:  # noqa: BLE001, S110 - no app state (tests, CLI): ask the database
        pass
    try:
        status = str(get_workflow(execution_id).get("status") or "").lower()
    except HTTPException:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not tell whether run %s is still going: %s", execution_id, exc)
        return None
    return execution_id if status in _ACTIVE else None


def reset_state() -> None:
    """Forget deliveries and history (tests)."""
    _seen.clear()
    with _recent_lock:
        _recent.clear()
    with _issue_lock:
        _issue_runs.clear()
