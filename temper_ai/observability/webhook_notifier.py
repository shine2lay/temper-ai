"""POST a workflow's terminal outcome to a URL.

Everything temper knows about a run is either on a screen you have to be
watching or behind an API you have to poll. A long workflow that fails at
02:00 tells nobody. This closes that: one request when a run reaches a
terminal state, carrying enough to act on without a follow-up call.

Deliberately narrow. It fires on workflow completion, failure or
cancellation only — not on every event. A webhook that fires hundreds of
times per run is a log shipper, and this is a notification.

Failure policy: best-effort, and loud in the logs rather than in the run.
A workflow that already finished must not be recorded as failed because a
notification endpoint was down, so delivery problems are logged and
swallowed. Retries are bounded and quick; a webhook is not a queue.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

WEBHOOK_ENV_VAR = "TEMPER_WEBHOOK_URL"
TIMEOUT_ENV_VAR = "TEMPER_WEBHOOK_TIMEOUT"
# A run does not emit a "workflow.completed" event. It emits
# "workflow.started" and later *updates* that event's status, which reaches
# a notifier as "event.updated". Watching for a completion event therefore
# never fires — a unit test can pass against an event type the system does
# not produce, which is what happened here until an end-to-end run proved
# otherwise. Both shapes are handled: the update path this engine uses, and
# explicit terminal events in case another path emits them.
TERMINAL_EVENTS = ("workflow.completed", "workflow.failed", "workflow.cancelled")
TERMINAL_STATUSES = ("completed", "failed", "cancelled", "interrupted")
ROOT_EVENT = "workflow.started"
DEFAULT_TIMEOUT = 10.0
MAX_ATTEMPTS = 3


def configured_url() -> str | None:
    """The webhook URL, or None when notifications are off."""
    url = os.environ.get(WEBHOOK_ENV_VAR, "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        logger.warning("%s must be an http(s) URL, got %r — ignoring", WEBHOOK_ENV_VAR, url)
        return None
    return url


def _timeout() -> float:
    try:
        return float(os.environ.get(TIMEOUT_ENV_VAR, "") or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT


class WebhookNotifier:
    """Notifier that posts terminal workflow events to a URL.

    Implements the EventNotifier protocol, so it composes with the others
    through CompositeNotifier and needs no special handling in the executor.
    """

    def __init__(self, url: str | None = None, *, blocking: bool = False) -> None:
        self._url = url or configured_url()
        # Off the executor thread by default: a slow endpoint should not
        # hold up the run's own bookkeeping. Tests use blocking=True.
        self._blocking = blocking
        self._threads: list[threading.Thread] = []
        # The root event id per run, learned from workflow.started, so an
        # event.updated can be recognised as *the run* finishing rather than
        # any of the hundreds of node and call events that also update.
        self._root_event: dict[str, str] = {}
        self._root_data: dict[str, dict] = {}
        self._fired: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def notify_event(self, execution_id: str, event_type: str, data: dict) -> None:
        if not self._url:
            return

        if event_type == ROOT_EVENT:
            event_id = data.get("event_id")
            if event_id:
                self._root_event[execution_id] = str(event_id)
                self._root_data[execution_id] = dict(data)
            return

        status = str(data.get("status") or "")
        is_update = (
            event_type == "event.updated"
            and data.get("event_id")
            and str(data.get("event_id")) == self._root_event.get(execution_id)
            and status in TERMINAL_STATUSES
        )
        if not (is_update or event_type in TERMINAL_EVENTS):
            return

        if execution_id in self._fired:
            return
        self._fired.add(execution_id)

        merged = {**self._root_data.get(execution_id, {}), **data}
        payload = self._payload(execution_id, event_type, merged)
        if self._blocking:
            self._deliver(payload)
            return
        thread = threading.Thread(
            target=self._deliver, args=(payload,), name="temper-webhook", daemon=True
        )
        self._threads.append(thread)
        thread.start()

    def cleanup(self, execution_id: str) -> None:  # noqa: ARG002 - protocol
        # Give in-flight deliveries a moment; never block a run for long.
        for thread in self._threads:
            thread.join(timeout=_timeout())
        self._threads.clear()
        self._root_event.pop(execution_id, None)
        self._root_data.pop(execution_id, None)
        self._fired.discard(execution_id)

    def _payload(self, execution_id: str, event_type: str, data: dict) -> dict[str, Any]:
        """What a receiver needs to act without calling back for more."""
        status = str(data.get("status") or event_type.rsplit(".", 1)[-1])
        # Name the event for the receiver, not for us. Internally this
        # arrives as "event.updated" because the engine updates the root
        # event rather than emitting a completion event, but a subscriber
        # should not have to know that to match on it.
        return {
            "event": f"workflow.{status}",
            "execution_id": execution_id,
            "status": status,
            "workflow": data.get("name") or data.get("workflow_name"),
            "duration_seconds": data.get("duration_seconds"),
            "total_cost_usd": data.get("cost_usd") or data.get("total_cost_usd"),
            "total_tokens": data.get("total_tokens"),
            "error": data.get("error"),
        }

    def _deliver(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._url,  # type: ignore[arg-type]
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "temper-webhook/1"},
            method="POST",
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(request, timeout=_timeout()) as response:
                    if 200 <= response.status < 300:
                        return
                    logger.warning(
                        "webhook %s returned HTTP %s for run %s (attempt %d/%d)",
                        self._url, response.status, payload["execution_id"], attempt, MAX_ATTEMPTS,
                    )
            except urllib.error.HTTPError as exc:
                # 4xx is a configuration problem; retrying will not fix it.
                if 400 <= exc.code < 500:
                    logger.warning(
                        "webhook %s rejected run %s with HTTP %s — not retrying",
                        self._url, payload["execution_id"], exc.code,
                    )
                    return
                logger.warning("webhook %s failed for run %s: HTTP %s (attempt %d/%d)",
                               self._url, payload["execution_id"], exc.code, attempt, MAX_ATTEMPTS)
            except Exception as exc:
                logger.warning("webhook %s failed for run %s: %s (attempt %d/%d)",
                               self._url, payload["execution_id"], exc, attempt, MAX_ATTEMPTS)
        logger.error(
            "webhook %s gave up on run %s after %d attempts — the run itself is unaffected",
            self._url, payload["execution_id"], MAX_ATTEMPTS,
        )
