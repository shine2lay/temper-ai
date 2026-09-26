"""Slack Socket Mode: temper opens a websocket to Slack, so Slack needs no
public URL to reach it.

    apps.connections.open (app-level token) -> a wss:// URL
    Slack sends {"type": "hello"}, then envelopes:
        {"envelope_id", "type": "slash_commands"|"interactive"|"events_api", "payload", ...}
    each acked with {"envelope_id": ...} within 3 seconds, or Slack retries
    (events) or shows the person an error (commands, clicks).
    {"type": "disconnect"} means reconnect (Slack refreshes links every few
    hours).

Slack sends each envelope to ONE of an app's open connections, so exactly
one process may hold the socket: the server, and only one server
(``TEMPER_SLACK=0`` on any other).

The ack is sent here, in the reading thread, before any work; the handler
runs on its own pool and answers through the Web API.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

BACKOFF_S = (1, 2, 5, 10, 30, 60)
RECV_TIMEOUT_S = 1.0
OPEN_TIMEOUT_S = 10.0


def _connect(url: str) -> Any:
    from websockets.sync.client import connect

    return connect(url, open_timeout=OPEN_TIMEOUT_S, ping_interval=30, ping_timeout=20, max_size=2**22)


class SocketMode:
    def __init__(self, open_url: Callable[[], str], on_envelope: Callable[[dict[str, Any]], None],
                 connect: Callable[[str], Any] = _connect, sleep: Callable[[float], Any] | None = None) -> None:
        self._open_url = open_url
        self._on_envelope = on_envelope
        self._connect = connect
        self._stop = threading.Event()
        self._sleep = sleep or self._stop.wait
        self._thread: threading.Thread | None = None
        self.connected = False
        self.connected_at: str | None = None
        self.last_envelope_at: str | None = None
        self.last_error: str | None = None
        self.connects = 0
        self.envelopes = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="slack-socket", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def status(self) -> dict[str, Any]:
        return {"connected": self.connected, "connected_at": self.connected_at, "connects": self.connects,
                "envelopes": self.envelopes, "last_envelope_at": self.last_envelope_at,
                "last_error": self.last_error}

    def _loop(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                clean = self.run_once()
                failures = 0 if clean else failures + 1
            except Exception as exc:  # noqa: BLE001 - network, auth, Slack: back off and try again
                self.last_error = f"{type(exc).__name__}: {exc}"
                failures += 1
                logger.warning("Slack socket: %s", self.last_error)
            finally:
                self.connected = False
            if failures and not self._stop.is_set():
                self._sleep(BACKOFF_S[min(failures - 1, len(BACKOFF_S) - 1)])

    def run_once(self) -> bool:
        """One connection, until Slack or ``stop`` ends it. True if it ended
        the way Slack asks for (a disconnect message), so no back-off."""
        url = self._open_url()
        with self._connect(url) as ws:
            while not self._stop.is_set():
                try:
                    raw = ws.recv(timeout=RECV_TIMEOUT_S)
                except TimeoutError:
                    continue
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "hello":
                    self.connected = True
                    self.connects += 1
                    self.connected_at = datetime.now(UTC).isoformat(timespec="seconds")
                    self.last_error = None
                    logger.info("Slack socket connected (%s)", (msg.get("debug_info") or {}).get("host", "?"))
                    continue
                if kind == "disconnect":
                    logger.info("Slack socket: disconnect (%s); reconnecting", msg.get("reason"))
                    return True
                envelope_id = msg.get("envelope_id")
                if envelope_id:
                    ws.send(json.dumps({"envelope_id": envelope_id}))
                    self.envelopes += 1
                    self.last_envelope_at = datetime.now(UTC).isoformat(timespec="seconds")
                    started = time.monotonic()
                    try:
                        self._on_envelope(msg)
                    except Exception:  # noqa: BLE001
                        logger.exception("Slack socket: could not hand off a %s envelope", kind)
                    if time.monotonic() - started > 1:
                        logger.warning("Slack socket: handing off a %s envelope took %.1fs", kind,
                                       time.monotonic() - started)
        return False
